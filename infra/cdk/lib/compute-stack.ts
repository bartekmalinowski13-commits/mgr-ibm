import { CfnOutput, Duration, RemovalPolicy } from "aws-cdk-lib";
import * as appscaling from "aws-cdk-lib/aws-applicationautoscaling";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secrets from "aws-cdk-lib/aws-secretsmanager";
import type { Construct } from "constructs";
import { BaseStack, type BaseStackProps } from "./base-stack";
import { type DataStack, filesBucketName, type QueueName } from "./data-stack";
import type { IdentityStack } from "./identity-stack";
import { acknowledge } from "./nag";

export interface ComputeStackProps extends BaseStackProps {
  readonly vpc: ec2.IVpc;
  readonly logsKey: kms.IKey;
  readonly data: DataStack;
  readonly identity: IdentityStack;
}

/** EU regions where Bedrock may be called (EU cross-region inference profiles). */
// regions an EU cross-region inference profile may route to (all EU, ADR-0002)
export const BEDROCK_REGIONS = [
  "eu-central-1",
  "eu-west-1",
  "eu-west-3",
  "eu-north-1",
  "eu-south-1",
  "eu-south-2",
];
const GATEWAY_PORT = 4000;
const API_PORT = 8000;
/** Where the Dockerfile puts the RDS global CA bundle (deploy/docker/python-service.Dockerfile). */
export const RDS_CA_BUNDLE_PATH = "/etc/ssl/rds/global-bundle.pem";

interface WorkerSpec {
  readonly name: string;
  readonly image: string;
  readonly module: string;
  readonly queue: QueueName;
  readonly subnets: ec2.SubnetType;
  readonly cpu: number;
  readonly memory: number;
  readonly maxTasks: number;
  readonly llm: boolean;
}

/**
 * ECS Fargate (ADR-0003): API behind an ALB that accepts traffic only from CloudFront
 * (managed prefix list + secret origin header), queue workers that scale on queue
 * depth, the LLM gateway (LiteLLM) reachable through Service Connect, and a one-off
 * migration task definition run by the pipeline. Tasks run as non-root with a
 * read-only root file system; the ingest worker (untrusted files) runs in isolated
 * subnets with no route to the internet.
 */
export class ComputeStack extends BaseStack {
  readonly cluster: ecs.Cluster;
  readonly loadBalancer: elbv2.ApplicationLoadBalancer;
  readonly originSecret: secrets.Secret;
  readonly apiService: ecs.FargateService;
  readonly workers: Record<string, ecs.FargateService> = {};
  readonly albProtocol: elbv2.ApplicationProtocol;

  constructor(scope: Construct, id: string, props: ComputeStackProps) {
    super(scope, id, props);
    const { config, vpc, data, identity, logsKey } = props;
    const removal = config.production ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY;
    const registryAccount = config.imageRegistry.split(".")[0] ?? config.account;
    const repos = new Map<string, ecr.IRepository>();
    const image = (name: string) => {
      let repo = repos.get(name);
      if (!repo) {
        repo = ecr.Repository.fromRepositoryArn(
          this,
          `${name}Repo`,
          `arn:aws:ecr:${config.region}:${registryAccount}:repository/${name}`,
        );
        repos.set(name, repo);
      }
      return ecs.ContainerImage.fromEcrRepository(repo, config.imageTag);
    };

    this.cluster = new ecs.Cluster(this, "Cluster", {
      vpc,
      clusterName: `bomagent-${config.name}`,
      containerInsightsV2: ecs.ContainerInsights.ENHANCED,
      enableFargateCapacityProviders: true,
    });
    const namespace = this.cluster.addDefaultCloudMapNamespace({
      name: "bomagent.internal",
      useForServiceConnect: true,
    });

    const computeKey = new kms.Key(this, "ComputeKey", {
      alias: `alias/bomagent-${config.name}-compute`,
      description: "Internal secrets of the compute layer (gateway key, origin header)",
      enableKeyRotation: true,
      removalPolicy: removal,
    });
    const gatewayKey = new secrets.Secret(this, "GatewayKey", {
      description: "LiteLLM master key (internal calls from API and workers to the LLM gateway)",
      encryptionKey: computeKey,
      generateSecretString: { excludePunctuation: true, passwordLength: 48 },
      removalPolicy: removal,
    });
    this.originSecret = new secrets.Secret(this, "OriginVerify", {
      description:
        "Header value CloudFront adds to API requests; the ALB rejects requests without it",
      encryptionKey: computeKey,
      generateSecretString: { excludePunctuation: true, passwordLength: 48 },
      removalPolicy: removal,
    });
    for (const s of [gatewayKey, this.originSecret]) {
      acknowledge(
        s,
        "AwsSolutions-SMG4",
        "Static shared secret between our own components; rotated by redeploying (runbook: rotate-internal-secrets).",
      );
    }

    const logGroup = (name: string) =>
      new logs.LogGroup(this, `${name}Logs`, {
        logGroupName: `/bomagent/${config.name}/${name}`,
        encryptionKey: logsKey,
        retention: config.production ? logs.RetentionDays.ONE_YEAR : logs.RetentionDays.ONE_MONTH,
        removalPolicy: removal,
      });

    const commonEnv: Record<string, string> = {
      BOMAGENT_ENVIRONMENT: config.name,
      BOMAGENT_AWS_REGION: config.region,
      BOMAGENT_DATABASE_HOST: data.cluster.clusterEndpoint.hostname,
      // RDS global CA bundle baked into the images: connections use sslmode=verify-full
      BOMAGENT_DB_SSL_ROOT_CERT: RDS_CA_BUNDLE_PATH,
      BOMAGENT_FILES_BUCKET: data.filesBucket.bucketName,
      BOMAGENT_LOG_JSON: "true",
    };
    // Imported by ARN: reading them must not change the data stack (no cross-stack cycle).
    // Decryption with the data key is granted on the task execution roles below.
    const roleSecret = (role: keyof DataStack["roleSecrets"]) =>
      secrets.Secret.fromSecretCompleteArn(this, `${role}Ref`, data.roleSecrets[role].secretArn);
    const appDbPassword = ecs.Secret.fromSecretsManager(roleSecret("bomagent_app"), "password");
    const platformDbPassword = ecs.Secret.fromSecretsManager(
      roleSecret("bomagent_platform"),
      "password",
    );
    const migratorDbPassword = ecs.Secret.fromSecretsManager(
      roleSecret("bomagent_migrator"),
      "password",
    );
    const tenantObjects = `arn:aws:s3:::${filesBucketName(config)}/tenants/*`;
    /** Tenant files: objects under tenants/ only, with the data key via S3 only. */
    const grantFiles = (def: ecs.TaskDefinition, write: boolean) => {
      def.addToTaskRolePolicy(
        new iam.PolicyStatement({
          sid: "TenantObjects",
          actions: write ? ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"] : ["s3:GetObject"],
          resources: [tenantObjects],
        }),
      );
      def.addToTaskRolePolicy(
        new iam.PolicyStatement({
          sid: "DataKeyViaS3",
          actions: write ? ["kms:Decrypt", "kms:GenerateDataKey"] : ["kms:Decrypt"],
          resources: [data.dataKey.keyArn],
          conditions: { StringEquals: { "kms:ViaService": `s3.${config.region}.amazonaws.com` } },
        }),
      );
      acknowledge(
        def,
        `AwsSolutions-IAM5[Resource::${tenantObjects}]`,
        "Object keys are tenant-prefixed (tenants/<tenant_id>/...); the application enforces the active tenant on every key (ObjectStore) and RLS on metadata.",
      );
    };
    const decryptDataSecrets = new iam.PolicyStatement({
      sid: "DecryptRoleSecrets",
      actions: ["kms:Decrypt"],
      resources: [data.dataKey.keyArn],
      conditions: {
        StringEquals: { "kms:ViaService": `secretsmanager.${config.region}.amazonaws.com` },
      },
    });

    /** Task definition with a non-root, read-only container and a writable /tmp. */
    const taskDefinition = (
      name: string,
      opts: {
        image: string;
        module?: string;
        cpu: number;
        memory: number;
        env: Record<string, string>;
        secrets: Record<string, ecs.Secret>;
        port?: number;
        command?: string[];
      },
    ) => {
      const def = new ecs.FargateTaskDefinition(this, `${name}Task`, {
        cpu: opts.cpu,
        memoryLimitMiB: opts.memory,
        runtimePlatform: {
          cpuArchitecture: ecs.CpuArchitecture.ARM64,
          operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
        },
      });
      def.addVolume({ name: "tmp" });
      def.addToExecutionRolePolicy(decryptDataSecrets);
      const container = def.addContainer(name, {
        image: image(opts.image),
        user: "10001:10001",
        readonlyRootFilesystem: true,
        environment: { ...opts.env, ...(opts.module ? { BOMAGENT_MODULE: opts.module } : {}) },
        secrets: opts.secrets,
        command: opts.command,
        logging: ecs.LogDrivers.awsLogs({ streamPrefix: name, logGroup: logGroup(name) }),
        portMappings: opts.port
          ? [{ containerPort: opts.port, name: name === "gateway" ? "litellm" : name }]
          : [],
      });
      container.addMountPoints({ containerPath: "/tmp", sourceVolume: "tmp", readOnly: false });
      acknowledge(
        def,
        "AwsSolutions-IAM5[Resource::*]",
        "ecr:GetAuthorizationToken and CloudWatch Logs stream actions created by ECS for the execution role do not support resource scoping.",
      );
      acknowledge(
        def,
        "AwsSolutions-ECS2",
        "Only non-secret configuration is passed as environment variables; secrets come from Secrets Manager.",
      );
      return def;
    };

    // ---------------------------------------------------------------- LLM gateway
    const gatewaySg = new ec2.SecurityGroup(this, "GatewaySg", { vpc, description: "LLM gateway" });
    const gatewayTask = taskDefinition("gateway", {
      image: "bomagent-llm-gateway",
      cpu: 512,
      memory: 1024,
      env: {
        AWS_REGION: config.region,
        LITELLM_LOG: "ERROR",
        // use the price map bundled with the pinned version: no fetch from GitHub at start
        LITELLM_LOCAL_MODEL_COST_MAP: "True",
      },
      secrets: { LITELLM_MASTER_KEY: ecs.Secret.fromSecretsManager(gatewayKey) },
      port: GATEWAY_PORT,
    });
    gatewayTask.addToTaskRolePolicy(
      new iam.PolicyStatement({
        sid: "BedrockInvokeEuOnly",
        actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        resources: [
          "arn:aws:bedrock:*::foundation-model/*",
          `arn:aws:bedrock:*:${config.account}:inference-profile/eu.*`,
        ],
        conditions: { StringEquals: { "aws:RequestedRegion": BEDROCK_REGIONS } },
      }),
    );
    for (const resource of [
      "arn:aws:bedrock:*::foundation-model/*",
      `arn:aws:bedrock:*:${config.account}:inference-profile/eu.*`,
    ]) {
      acknowledge(
        gatewayTask,
        `AwsSolutions-IAM5[Resource::${resource}]`,
        "Model ids and EU cross-region inference profiles; calls are restricted to EU regions by the aws:RequestedRegion condition.",
      );
    }
    const gateway = new ecs.FargateService(this, "Gateway", {
      cluster: this.cluster,
      taskDefinition: gatewayTask,
      desiredCount: config.production ? 2 : 1,
      minHealthyPercent: 100,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [gatewaySg],
      circuitBreaker: { rollback: true },
      serviceConnectConfiguration: {
        namespace: namespace.namespaceName,
        services: [{ portMappingName: "litellm", dnsName: "litellm", port: GATEWAY_PORT }],
      },
    });
    const gatewayUrl = `http://litellm:${GATEWAY_PORT}`;
    const llmEnv = { BOMAGENT_LLM_GATEWAY_URL: gatewayUrl };
    const llmSecrets = { BOMAGENT_LLM_GATEWAY_KEY: ecs.Secret.fromSecretsManager(gatewayKey) };

    // ---------------------------------------------------------------- API + ALB
    const albSg = new ec2.SecurityGroup(this, "AlbSg", {
      vpc,
      description: "API load balancer: CloudFront origin-facing addresses only",
      allowAllOutbound: false,
    });
    const albLogs = new s3.Bucket(this, "AlbLogs", {
      encryption: s3.BucketEncryption.S3_MANAGED, // ALB access logs support SSE-S3 only
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      lifecycleRules: [{ expiration: Duration.days(config.production ? 400 : 30) }],
      removalPolicy: removal,
      autoDeleteObjects: !config.production,
    });
    this.loadBalancer = new elbv2.ApplicationLoadBalancer(this, "Alb", {
      vpc,
      internetFacing: true,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      securityGroup: albSg,
      dropInvalidHeaderFields: true,
    });
    this.loadBalancer.logAccessLogs(albLogs, "alb");
    acknowledge(
      albLogs,
      "AwsSolutions-S1",
      "Destination of ALB access logs; logging this bucket again would point the data stack at compute (stack cycle).",
    );
    const https = !!config.albCertificateArn;
    this.albProtocol = https ? elbv2.ApplicationProtocol.HTTPS : elbv2.ApplicationProtocol.HTTP;
    const listenerPort = https ? 443 : 80;
    albSg.addIngressRule(
      ec2.Peer.prefixList(config.cloudFrontPrefixListId),
      ec2.Port.tcp(listenerPort),
      "CloudFront origin-facing",
    );
    const listener = this.loadBalancer.addListener("Listener", {
      port: listenerPort,
      protocol: this.albProtocol,
      certificates: https
        ? [elbv2.ListenerCertificate.fromArn(config.albCertificateArn as string)]
        : undefined,
      sslPolicy: https ? elbv2.SslPolicy.RECOMMENDED_TLS : undefined,
      open: false,
      defaultAction: elbv2.ListenerAction.fixedResponse(403, {
        contentType: "application/problem+json",
        messageBody: '{"title":"Forbidden","status":403}',
      }),
    });

    const apiSg = new ec2.SecurityGroup(this, "ApiSg", { vpc, description: "API tasks" });
    apiSg.addIngressRule(albSg, ec2.Port.tcp(API_PORT), "from the ALB");
    albSg.addEgressRule(apiSg, ec2.Port.tcp(API_PORT), "to API tasks");
    const apiTask = taskDefinition("api", {
      image: "bomagent-api",
      module: "bomagent_api",
      cpu: 1024,
      memory: 2048,
      port: API_PORT,
      env: {
        ...commonEnv,
        ...llmEnv,
        BOMAGENT_SERVICE_NAME: "bomagent-api",
        BOMAGENT_AUTH_MODE: "oidc",
        BOMAGENT_OIDC_ISSUER: identity.issuer,
        BOMAGENT_OIDC_AUDIENCE: identity.webClient.userPoolClientId,
        BOMAGENT_OIDC_JWKS_URL: `${identity.issuer}/.well-known/jwks.json`,
        // SSO per organisation: identity providers are federated in this pool / client
        BOMAGENT_COGNITO_USER_POOL_ID: identity.userPool.userPoolId,
        BOMAGENT_COGNITO_CLIENT_ID: identity.webClient.userPoolClientId,
        BOMAGENT_COGNITO_DOMAIN: identity.hostedDomain,
        BOMAGENT_INGEST_QUEUE_URL: data.queues.ingest.queueUrl,
        BOMAGENT_RUNS_QUEUE_URL: data.queues.runs.queueUrl,
        BOMAGENT_KB_QUEUE_URL: data.queues.kb.queueUrl,
      },
      secrets: {
        BOMAGENT_DATABASE_PASSWORD: appDbPassword,
        BOMAGENT_PLATFORM_DATABASE_PASSWORD: platformDbPassword,
        ...llmSecrets,
      },
    });
    grantFiles(apiTask, true);
    for (const q of Object.values(data.queues)) q.grantSendMessages(apiTask.taskRole);
    apiTask.addToTaskRolePolicy(
      new iam.PolicyStatement({
        sid: "FederateOrganisationIdentityProviders",
        actions: [
          "cognito-idp:CreateIdentityProvider",
          "cognito-idp:UpdateIdentityProvider",
          "cognito-idp:DeleteIdentityProvider",
          "cognito-idp:DescribeIdentityProvider",
          "cognito-idp:DescribeUserPoolClient",
          "cognito-idp:UpdateUserPoolClient",
        ],
        resources: [identity.userPool.userPoolArn],
      }),
    );
    for (const action of ["kms:GenerateDataKey*", "kms:ReEncrypt*"]) {
      acknowledge(
        apiTask,
        `AwsSolutions-IAM5[Action::${action}]`,
        "Producer to SQS queues with SSE-KMS: data-key actions on the queues' key only (CDK grant).",
      );
    }
    this.apiService = new ecs.FargateService(this, "Api", {
      cluster: this.cluster,
      taskDefinition: apiTask,
      desiredCount: config.production ? 2 : 1,
      minHealthyPercent: 100,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [apiSg],
      circuitBreaker: { rollback: true },
      serviceConnectConfiguration: { namespace: namespace.namespaceName },
    });
    this.apiService.node.addDependency(gateway);
    const target = new elbv2.ApplicationTargetGroup(this, "ApiTargets", {
      vpc,
      port: API_PORT,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [this.apiService],
      healthCheck: { path: "/healthz", healthyHttpCodes: "200", interval: Duration.seconds(15) },
      deregistrationDelay: Duration.seconds(30),
    });
    listener.addAction("FromCloudFront", {
      priority: 10,
      conditions: [
        elbv2.ListenerCondition.httpHeader("X-Origin-Verify", [
          this.originSecret.secretValue.unsafeUnwrap(), // CloudFormation dynamic reference, not plaintext
        ]),
      ],
      action: elbv2.ListenerAction.forward([target]),
    });
    const apiScaling = this.apiService.autoScaleTaskCount({
      minCapacity: config.production ? 2 : 1,
      maxCapacity: config.production ? 10 : 2,
    });
    apiScaling.scaleOnCpuUtilization("Cpu", { targetUtilizationPercent: 60 });

    // ---------------------------------------------------------------- workers
    const workerSpecs: WorkerSpec[] = [
      {
        name: "ingest",
        image: "bomagent-ingest-worker",
        module: "bomagent_ingest",
        queue: "ingest",
        subnets: ec2.SubnetType.PRIVATE_ISOLATED, // untrusted files: no internet route
        cpu: 1024,
        memory: 2048,
        maxTasks: 4,
        llm: false,
      },
      {
        name: "agents",
        image: "bomagent-agent-worker",
        module: "bomagent_agent_worker",
        queue: "runs",
        subnets: ec2.SubnetType.PRIVATE_WITH_EGRESS,
        cpu: 1024,
        memory: 2048,
        maxTasks: config.production ? 20 : 3,
        llm: true,
      },
      {
        name: "kbindexer",
        image: "bomagent-kb-indexer",
        module: "bomagent_kb_indexer",
        queue: "kb",
        subnets: ec2.SubnetType.PRIVATE_WITH_EGRESS,
        cpu: 1024,
        memory: 2048,
        maxTasks: 3,
        llm: true,
      },
    ];
    for (const spec of workerSpecs) {
      const queue = data.queues[spec.queue];
      const isolated = spec.subnets === ec2.SubnetType.PRIVATE_ISOLATED;
      const sg = new ec2.SecurityGroup(this, `${spec.name}Sg`, {
        vpc,
        description: `${spec.name} worker (no inbound)`,
        // isolated subnets route only to the VPC, the S3 gateway endpoint (own account)
        // and the interface endpoints: HTTPS and PostgreSQL are all a parser may use
        allowAllOutbound: !isolated,
      });
      if (isolated) {
        sg.addEgressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), "VPC endpoints and S3 (HTTPS)");
        sg.addEgressRule(
          ec2.Peer.securityGroupId(data.databaseSecurityGroup.securityGroupId),
          ec2.Port.tcp(5432),
          "PostgreSQL",
        );
      }
      const task = taskDefinition(spec.name, {
        image: spec.image,
        module: spec.module,
        cpu: spec.cpu,
        memory: spec.memory,
        env: {
          ...commonEnv,
          ...(spec.llm ? llmEnv : {}),
          BOMAGENT_SERVICE_NAME: `bomagent-${spec.name}`,
          BOMAGENT_QUEUE_URL: queue.queueUrl,
          BOMAGENT_QUEUE_WAIT_SECONDS: "20",
        },
        secrets: { BOMAGENT_DATABASE_PASSWORD: appDbPassword, ...(spec.llm ? llmSecrets : {}) },
      });
      queue.grantConsumeMessages(task.taskRole);
      grantFiles(task, spec.queue !== "ingest");
      const service = new ecs.FargateService(this, `${spec.name}Service`, {
        cluster: this.cluster,
        taskDefinition: task,
        desiredCount: 1,
        minHealthyPercent: 100, // a draining worker finishes its message first
        vpcSubnets: { subnetType: spec.subnets },
        securityGroups: [sg],
        circuitBreaker: { rollback: true },
        ...(spec.llm
          ? { serviceConnectConfiguration: { namespace: namespace.namespaceName } }
          : {}),
      });
      if (spec.llm) service.node.addDependency(gateway);
      const scaling = service.autoScaleTaskCount({ minCapacity: 1, maxCapacity: spec.maxTasks });
      scaling.scaleOnMetric("QueueDepth", {
        metric: queue.metricApproximateNumberOfMessagesVisible({ period: Duration.minutes(1) }),
        scalingSteps: [
          { upper: 0, change: -1 },
          { lower: 5, change: +1 },
          { lower: 50, change: +3 },
        ],
        adjustmentType: appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
        cooldown: Duration.minutes(2),
      });
      this.workers[spec.name] = service;
    }

    // ---------------------------------------------------------------- migrations
    // 1) dbbootstrap: the only task with the Aurora master secret. Creates the roles, sets
    //    their passwords from their secrets, installs pgvector and hands the database to
    //    the migrator (bomagent-migrate bootstrap; idempotent, re-run to rotate passwords).
    const adminSecret = secrets.Secret.fromSecretCompleteArn(
      this,
      "DbAdminRef",
      data.cluster.secret?.secretArn ?? "",
    );
    const dbBootstrap = taskDefinition("dbbootstrap", {
      image: "bomagent-migrate",
      cpu: 256,
      memory: 512,
      env: { ...commonEnv },
      secrets: {
        BOMAGENT_ADMIN_USER: ecs.Secret.fromSecretsManager(adminSecret, "username"),
        BOMAGENT_ADMIN_PASSWORD: ecs.Secret.fromSecretsManager(adminSecret, "password"),
        BOMAGENT_MIGRATOR_PASSWORD: migratorDbPassword,
        BOMAGENT_APP_PASSWORD: appDbPassword,
        BOMAGENT_PLATFORM_PASSWORD: platformDbPassword,
      },
      command: ["bomagent-migrate", "bootstrap"],
    });
    // 2) migrate: schema migrations as the migrator (owner of all objects), nothing else
    const migrate = taskDefinition("migrate", {
      image: "bomagent-migrate",
      cpu: 256,
      memory: 512,
      env: { ...commonEnv },
      secrets: { MIGRATOR_PASSWORD: migratorDbPassword },
      // passwords are alphanumeric (generated without punctuation): safe inside the URL
      command: [
        "sh",
        "-c",
        'export BOMAGENT_MIGRATOR_DATABASE_URL="postgresql+psycopg://bomagent_migrator:$MIGRATOR_PASSWORD@$BOMAGENT_DATABASE_HOST:5432/bomagent?sslmode=verify-full&sslrootcert=$BOMAGENT_DB_SSL_ROOT_CERT" && exec bomagent-migrate upgrade',
      ],
    });

    // ---------------------------------------------------------------- database access
    const dbClients = [
      apiSg,
      ...Object.values(this.workers).flatMap((s) => s.connections.securityGroups),
    ];
    const migrateSg = new ec2.SecurityGroup(this, "MigrateSg", {
      vpc,
      description: "migration task",
    });
    // rules live in this stack: the data stack must not depend on compute (no cycle)
    [...dbClients, migrateSg].forEach((sg, i) => {
      new ec2.CfnSecurityGroupIngress(this, `DbFromTasks${i}`, {
        groupId: data.databaseSecurityGroup.securityGroupId,
        sourceSecurityGroupId: sg.securityGroupId,
        ipProtocol: "tcp",
        fromPort: 5432,
        toPort: 5432,
        description: "PostgreSQL from application tasks",
      });
    });
    gatewaySg.addIngressRule(apiSg, ec2.Port.tcp(GATEWAY_PORT), "LLM gateway from API");
    for (const name of ["agents", "kbindexer"]) {
      for (const sg of this.workers[name]?.connections.securityGroups ?? []) {
        gatewaySg.addIngressRule(sg, ec2.Port.tcp(GATEWAY_PORT), `LLM gateway from ${name}`);
      }
    }

    new CfnOutput(this, "DbBootstrapTaskDefinition", { value: dbBootstrap.taskDefinitionArn });
    new CfnOutput(this, "MigrationTaskDefinition", { value: migrate.taskDefinitionArn });
    new CfnOutput(this, "MigrationSecurityGroup", { value: migrateSg.securityGroupId });
    new CfnOutput(this, "ApiLoadBalancer", { value: this.loadBalancer.loadBalancerDnsName });
  }
}
