import { RemovalPolicy, type StackProps } from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as logs from "aws-cdk-lib/aws-logs";
import type { Construct } from "constructs";
import { BaseStack } from "./base-stack";
import type { EnvConfig } from "./config";
import { acknowledge } from "./nag";

export const VPC_CIDR = "10.40.0.0/16";

export interface NetworkStackProps extends StackProps {
  readonly config: EnvConfig;
}

/**
 * VPC with three tiers: public (ALB, NAT), app (egress through NAT, e.g. LLM providers
 * on the allowlist) and isolated (database, sandboxed parsers - no route to the
 * internet; AWS APIs only through VPC endpoints). Also the KMS key for logs.
 */
export class NetworkStack extends BaseStack {
  readonly vpc: ec2.Vpc;
  readonly logsKey: kms.Key;
  readonly endpointsSecurityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: NetworkStackProps) {
    super(scope, id, props);
    const { config } = props;

    this.logsKey = new kms.Key(this, "LogsKey", {
      alias: `alias/bomagent-${config.name}-logs`,
      description: "CloudWatch Logs encryption (all BOM Agent log groups)",
      enableKeyRotation: true,
      removalPolicy: config.production ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
    });
    this.logsKey.addToResourcePolicy(
      new iam.PolicyStatement({
        principals: [new iam.ServicePrincipal(`logs.${config.region}.amazonaws.com`)],
        actions: [
          "kms:Encrypt*",
          "kms:Decrypt*",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:Describe*",
        ],
        resources: ["*"],
        conditions: {
          ArnLike: {
            "kms:EncryptionContext:aws:logs:arn": `arn:aws:logs:${config.region}:${config.account}:*`,
          },
        },
      }),
    );

    const flowLogs = new logs.LogGroup(this, "FlowLogs", {
      encryptionKey: this.logsKey,
      retention: config.production ? logs.RetentionDays.ONE_YEAR : logs.RetentionDays.ONE_MONTH,
      removalPolicy: config.production ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
    });

    this.vpc = new ec2.Vpc(this, "Vpc", {
      ipAddresses: ec2.IpAddresses.cidr(VPC_CIDR),
      // explicit AZs: synth must not look anything up in AWS (no credentials in CI)
      availabilityZones: this.availabilityZones,
      natGateways: config.natGateways,
      restrictDefaultSecurityGroup: true,
      subnetConfiguration: [
        { name: "public", subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: "app", subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 22 },
        { name: "isolated", subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
      flowLogs: {
        all: {
          destination: ec2.FlowLogDestination.toCloudWatchLogs(flowLogs),
          trafficType: ec2.FlowLogTrafficType.ALL,
        },
      },
    });

    acknowledge(
      this.vpc,
      "CloudFormation-Validate::W3010",
      "Availability zones are fixed on purpose: synth runs without AWS credentials (no lookups); eu-central-1a/b/c exist in every account.",
    );
    const s3Endpoint = this.vpc.addGatewayEndpoint("S3", {
      service: ec2.GatewayVpcEndpointAwsService.S3,
      subnets: [
        { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
        { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      ],
    });
    // S3 from the VPC reaches only this account's buckets and the ECR image layers: a
    // compromised parser cannot copy files to a bucket of somebody else (exfiltration)
    s3Endpoint.addToPolicy(
      new iam.PolicyStatement({
        sid: "OwnAccountBuckets",
        principals: [new iam.AnyPrincipal()],
        actions: ["s3:*"],
        resources: ["*"],
        conditions: { StringEquals: { "aws:ResourceAccount": props.config.account } },
      }),
    );
    s3Endpoint.addToPolicy(
      new iam.PolicyStatement({
        sid: "EcrImageLayers",
        principals: [new iam.AnyPrincipal()],
        actions: ["s3:GetObject"],
        resources: [`arn:aws:s3:::prod-${props.config.region}-starport-layer-bucket/*`],
      }),
    );
    this.endpointsSecurityGroup = new ec2.SecurityGroup(this, "EndpointsSg", {
      vpc: this.vpc,
      description: "Interface VPC endpoints: HTTPS from inside the VPC only",
      allowAllOutbound: false,
    });
    this.endpointsSecurityGroup.addIngressRule(
      ec2.Peer.ipv4(VPC_CIDR),
      ec2.Port.tcp(443),
      "HTTPS from the VPC",
    );
    const services: Record<string, ec2.InterfaceVpcEndpointAwsService> = {
      Sqs: ec2.InterfaceVpcEndpointAwsService.SQS,
      SecretsManager: ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
      EcrApi: ec2.InterfaceVpcEndpointAwsService.ECR,
      EcrDocker: ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
      Logs: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
      Kms: ec2.InterfaceVpcEndpointAwsService.KMS,
      Sts: ec2.InterfaceVpcEndpointAwsService.STS,
      BedrockRuntime: ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
    };
    for (const [name, service] of Object.entries(services)) {
      this.vpc.addInterfaceEndpoint(name, {
        service,
        subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
        securityGroups: [this.endpointsSecurityGroup],
        privateDnsEnabled: true,
        open: false, // ingress is the explicit rule on the endpoints security group
      });
    }
  }
}
