import { CfnOutput, Duration, RemovalPolicy } from "aws-cdk-lib";
import * as accessanalyzer from "aws-cdk-lib/aws-accessanalyzer";
import * as backup from "aws-cdk-lib/aws-backup";
import * as cloudtrail from "aws-cdk-lib/aws-cloudtrail";
import * as cw from "aws-cdk-lib/aws-cloudwatch";
import * as cwActions from "aws-cdk-lib/aws-cloudwatch-actions";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as events from "aws-cdk-lib/aws-events";
import * as guardduty from "aws-cdk-lib/aws-guardduty";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as securityhub from "aws-cdk-lib/aws-securityhub";
import * as sns from "aws-cdk-lib/aws-sns";
import * as subs from "aws-cdk-lib/aws-sns-subscriptions";
import type { Construct } from "constructs";
import { BaseStack, type BaseStackProps } from "./base-stack";
import type { ComputeStack } from "./compute-stack";
import { type DataStack, filesBucketName } from "./data-stack";
import { siteBucketName } from "./edge-stack";
import { acknowledge } from "./nag";

// ------------------------------------------------------------------ observability
export interface ObservabilityStackProps extends BaseStackProps {
  readonly data: DataStack;
  readonly compute: ComputeStack;
}

/** Alarms on what users feel (5xx, unhealthy API) and on lost work (DLQs, stuck queues). */
export class ObservabilityStack extends BaseStack {
  readonly alarmTopic: sns.Topic;

  constructor(scope: Construct, id: string, props: ObservabilityStackProps) {
    super(scope, id, props);
    const { config, data, compute } = props;
    const key = new kms.Key(this, "AlarmsKey", {
      alias: `alias/bomagent-${config.name}-alarms`,
      enableKeyRotation: true,
      removalPolicy: config.production ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
    });
    key.grantEncryptDecrypt(new iam.ServicePrincipal("cloudwatch.amazonaws.com"));
    this.alarmTopic = new sns.Topic(this, "Alarms", {
      topicName: `bomagent-${config.name}-alarms`,
      masterKey: key,
      enforceSSL: true,
    });
    if (config.alarmEmail)
      this.alarmTopic.addSubscription(new subs.EmailSubscription(config.alarmEmail));
    const action = new cwActions.SnsAction(this.alarmTopic);
    const alarm = (a: cw.Alarm) => {
      a.addAlarmAction(action);
      a.addOkAction(action);
      return a;
    };

    for (const [name, dlq] of Object.entries(data.deadLetterQueues)) {
      alarm(
        dlq
          .metricApproximateNumberOfMessagesVisible({ period: Duration.minutes(5) })
          .createAlarm(this, `${name}DlqAlarm`, {
            alarmDescription: `Messages in the ${name} dead-letter queue: work failed repeatedly`,
            threshold: 0,
            comparisonOperator: cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluationPeriods: 1,
            treatMissingData: cw.TreatMissingData.NOT_BREACHING,
          }),
      );
    }
    alarm(
      data.queues.runs
        .metricApproximateAgeOfOldestMessage({ period: Duration.minutes(5) })
        .createAlarm(this, "RunsAgeAlarm", {
          alarmDescription: "A run waited more than 15 minutes for an agent worker",
          threshold: 900,
          evaluationPeriods: 2,
          treatMissingData: cw.TreatMissingData.NOT_BREACHING,
        }),
    );
    alarm(
      compute.loadBalancer.metrics
        .httpCodeTarget(elbv2.HttpCodeTarget.TARGET_5XX_COUNT, {
          period: Duration.minutes(5),
          statistic: "Sum",
        })
        .createAlarm(this, "Api5xxAlarm", {
          alarmDescription: "API returned server errors",
          threshold: 10,
          evaluationPeriods: 1,
          treatMissingData: cw.TreatMissingData.NOT_BREACHING,
        }),
    );
    alarm(
      compute.apiService
        .metricCpuUtilization({ period: Duration.minutes(5) })
        .createAlarm(this, "ApiCpuAlarm", {
          alarmDescription: "API tasks are saturated",
          threshold: 85,
          evaluationPeriods: 3,
        }),
    );
    new CfnOutput(this, "AlarmTopic", { value: this.alarmTopic.topicArn });
  }
}

// ------------------------------------------------------------------ backup vault (eu-west-1)
/** Destination of backup copies in the second EU region (ARCHITECTURE §12). */
export class BackupVaultStack extends BaseStack {
  readonly vault: backup.BackupVault;

  constructor(scope: Construct, id: string, props: BaseStackProps) {
    super(scope, id, props);
    const key = new kms.Key(this, "VaultKey", {
      alias: `alias/bomagent-${props.config.name}-backup-copy`,
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    this.vault = new backup.BackupVault(this, "Vault", {
      backupVaultName: `bomagent-${props.config.name}-copy`,
      encryptionKey: key,
      removalPolicy: RemovalPolicy.RETAIN,
      lockConfiguration: props.config.production ? { minRetention: Duration.days(7) } : undefined,
    });
  }
}

// ------------------------------------------------------------------ security baseline
export interface SecurityStackProps extends BaseStackProps {
  readonly data: DataStack;
  readonly copyVault: backup.IBackupVault;
}

/**
 * Account-level detection and recovery: GuardDuty (incl. Malware Protection for the
 * files bucket and ECS runtime monitoring), Security Hub (AWS FSBP + CIS), IAM Access
 * Analyzer, an account CloudTrail when there is no organisation trail, and AWS Backup
 * with copies to the second EU region.
 */
export class SecurityBaselineStack extends BaseStack {
  constructor(scope: Construct, id: string, props: SecurityStackProps) {
    super(scope, id, props);
    const { config, data } = props;
    const removal = config.production ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY;

    if (!config.organizationSecurityServices) {
      this.enableThreatDetection();
    }

    // Malware Protection for S3: uploads are scanned and tagged before parsing
    const bucket = filesBucketName(config);
    const malwareRole = new iam.Role(this, "MalwareProtectionRole", {
      assumedBy: new iam.ServicePrincipal("malware-protection-plan.guardduty.amazonaws.com"),
      description: "GuardDuty Malware Protection for S3 on the tenant files bucket",
    });
    malwareRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "ManageScanRule",
        actions: [
          "events:PutRule",
          "events:DeleteRule",
          "events:PutTargets",
          "events:RemoveTargets",
          "events:DescribeRule",
          "events:ListTargetsByRule",
        ],
        resources: [
          `arn:aws:events:${config.region}:${config.account}:rule/DO-NOT-DELETE-AmazonGuardDutyMalwareProtectionS3*`,
        ],
        conditions: {
          StringLike: { "events:ManagedBy": "malware-protection-plan.guardduty.amazonaws.com" },
        },
      }),
    );
    malwareRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "BucketNotifications",
        actions: [
          "s3:PutBucketNotification",
          "s3:GetBucketNotification",
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ],
        resources: [`arn:aws:s3:::${bucket}`],
      }),
    );
    malwareRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "ScanAndTagObjects",
        actions: [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:GetObjectTagging",
          "s3:GetObjectVersionTagging",
          "s3:PutObjectTagging",
          "s3:PutObjectVersionTagging",
          "s3:PutObject",
        ],
        resources: [`arn:aws:s3:::${bucket}/*`],
      }),
    );
    malwareRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "DecryptForScan",
        actions: ["kms:Decrypt", "kms:GenerateDataKey"],
        resources: [data.dataKey.keyArn],
        conditions: { StringEquals: { "kms:ViaService": `s3.${config.region}.amazonaws.com` } },
      }),
    );
    for (const finding of [
      `Resource::arn:aws:s3:::${bucket}/*`,
      `Resource::arn:aws:events:${config.region}:${config.account}:rule/DO-NOT-DELETE-AmazonGuardDutyMalwareProtectionS3*`,
    ]) {
      acknowledge(
        malwareRole,
        `AwsSolutions-IAM5[${finding}]`,
        "Scope required by GuardDuty Malware Protection for S3 (AWS documentation); limited to the files bucket and the service-managed rule.",
      );
    }
    new guardduty.CfnMalwareProtectionPlan(this, "FilesMalwareScan", {
      role: malwareRole.roleArn,
      protectedResource: { s3Bucket: { bucketName: bucket } },
      actions: { tagging: { status: "ENABLED" } },
    });

    if (!config.organizationSecurityServices) {
      this.enableSecurityHub();
    }
    new accessanalyzer.CfnAnalyzer(this, "AccessAnalyzer", {
      type: "ACCOUNT",
      analyzerName: `bomagent-${config.name}`,
    });

    if (!config.organizationTrail) {
      const trailKey = new kms.Key(this, "TrailKey", {
        alias: `alias/bomagent-${config.name}-trail`,
        enableKeyRotation: true,
        removalPolicy: RemovalPolicy.RETAIN,
      });
      const trailBucket = new s3.Bucket(this, "TrailBucket", {
        encryption: s3.BucketEncryption.KMS,
        encryptionKey: trailKey,
        blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
        enforceSSL: true,
        versioned: true,
        serverAccessLogsBucket: data.accessLogsBucket,
        serverAccessLogsPrefix: "trail/",
        removalPolicy: RemovalPolicy.RETAIN,
      });
      new cloudtrail.Trail(this, "Trail", {
        bucket: trailBucket,
        encryptionKey: trailKey,
        isMultiRegionTrail: true,
        includeGlobalServiceEvents: true,
        enableFileValidation: true,
        managementEvents: cloudtrail.ReadWriteType.ALL,
      });
    }

    // AWS Backup: daily, kept per environment, copied to eu-west-1
    const vaultKey = new kms.Key(this, "BackupKey", {
      alias: `alias/bomagent-${config.name}-backup`,
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const vault = new backup.BackupVault(this, "Vault", {
      backupVaultName: `bomagent-${config.name}`,
      encryptionKey: vaultKey,
      removalPolicy: removal,
    });
    const plan = new backup.BackupPlan(this, "Plan", {
      backupPlanName: `bomagent-${config.name}`,
      backupVault: vault,
      backupPlanRules: [
        new backup.BackupPlanRule({
          ruleName: "Daily",
          scheduleExpression: events.Schedule.cron({ hour: "2", minute: "0" }),
          deleteAfter: Duration.days(config.backupRetentionDays),
          copyActions: [
            {
              destinationBackupVault: props.copyVault,
              deleteAfter: Duration.days(config.backupRetentionDays),
            },
          ],
        }),
      ],
    });
    const selection = plan.addSelection("TenantData", {
      resources: [
        backup.BackupResource.fromArn(data.cluster.clusterArn),
        backup.BackupResource.fromArn(`arn:aws:s3:::${bucket}`),
      ],
      allowRestores: true,
    });
    for (const policy of [
      "AWSBackupServiceRolePolicyForBackup",
      "AWSBackupServiceRolePolicyForRestores",
      "AWSBackupServiceRolePolicyForS3Backup",
      "AWSBackupServiceRolePolicyForS3Restore",
    ]) {
      acknowledge(
        selection,
        `AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/${policy}]`,
        "AWS Backup service-role managed policies are the documented way to grant AWS Backup access to Aurora and S3.",
      );
    }
  }
  /** Account-level GuardDuty detector (skipped when the organisation manages it). */
  private enableThreatDetection(): void {
    new guardduty.CfnDetector(this, "GuardDuty", {
      enable: true,
      findingPublishingFrequency: "FIFTEEN_MINUTES",
      features: [
        { name: "S3_DATA_EVENTS", status: "ENABLED" },
        { name: "RDS_LOGIN_EVENTS", status: "ENABLED" },
        { name: "EBS_MALWARE_PROTECTION", status: "ENABLED" },
        {
          name: "RUNTIME_MONITORING",
          status: "ENABLED",
          additionalConfiguration: [{ name: "ECS_FARGATE_AGENT_MANAGEMENT", status: "ENABLED" }],
        },
      ],
    });
  }

  /** Security Hub with FSBP and CIS (skipped when the organisation manages it). */
  private enableSecurityHub(): void {
    const { region } = this.config;
    const hub = new securityhub.CfnHub(this, "SecurityHub", { enableDefaultStandards: false });
    for (const [id, arn] of [
      [
        "Fsbp",
        `arn:aws:securityhub:${region}::standards/aws-foundational-security-best-practices/v/1.0.0`,
      ],
      ["Cis", `arn:aws:securityhub:${region}::standards/cis-aws-foundations-benchmark/v/3.0.0`],
    ]) {
      new securityhub.CfnStandard(this, id as string, {
        standardsArn: arn as string,
      }).node.addDependency(hub);
    }
  }
}

// ------------------------------------------------------------------ CI/CD
/**
 * GitHub Actions deploy role via OIDC (no long-lived keys, ADR-0012). Trusted only from
 * the repository's matching GitHub environment (protect it with a deployment branch rule:
 * main only). It may assume the CDK bootstrap roles of this account and make exactly the
 * calls tools/deploy.sh makes after `cdk deploy`, scoped to this environment.
 */
export class CicdStack extends BaseStack {
  constructor(scope: Construct, id: string, props: BaseStackProps) {
    super(scope, id, props);
    const { config } = props;
    const { account, region } = config;
    const providerArn =
      config.githubOidcProviderArn ??
      new iam.CfnOIDCProvider(this, "GitHub", {
        url: "https://token.actions.githubusercontent.com",
        clientIdList: ["sts.amazonaws.com"],
      }).attrArn;
    const role = new iam.Role(this, "Deploy", {
      roleName: `bomagent-${config.name}-github-deploy`,
      description: "Assumed by GitHub Actions (environment-scoped) to run tools/deploy.sh",
      // a first deployment (Aurora, CloudFront) takes longer than an hour
      maxSessionDuration: Duration.hours(3),
      assumedBy: new iam.WebIdentityPrincipal(providerArn, {
        StringEquals: {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": `repo:${config.githubRepository}:environment:${config.name}`,
        },
      }),
    });
    const bootstrapRoles = `arn:aws:iam::${account}:role/cdk-hnb659fds-*-role-${account}-*`;
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: "AssumeCdkBootstrapRoles",
        actions: ["sts:AssumeRole"],
        resources: [bootstrapRoles],
      }),
    );
    // ---- calls of tools/deploy.sh (outputs, one-off tasks, web app upload, invalidation)
    const prefix = `BomAgent-${config.name}`;
    const stacks = [region, "us-east-1"].map(
      (r) => `arn:aws:cloudformation:${r}:${account}:stack/${prefix}-*/*`,
    );
    const cluster = `arn:aws:ecs:${region}:${account}:cluster/bomagent-${config.name}`;
    const taskDefs = `arn:aws:ecs:${region}:${account}:task-definition/BomAgent${config.name}Compute*`;
    const tasks = `arn:aws:ecs:${region}:${account}:task/bomagent-${config.name}/*`;
    const taskRoles = `arn:aws:iam::${account}:role/${prefix}-Compute-*`;
    const site = `arn:aws:s3:::${siteBucketName(config)}`;
    const distributions = `arn:aws:cloudfront::${account}:distribution/*`;
    // the WAF stack (us-east-1, no CDK bootstrap there) is deployed with these credentials
    const wafStack = `arn:aws:cloudformation:us-east-1:${account}:stack/${prefix}-Waf/*`;
    const wafChangeSets = `arn:aws:cloudformation:us-east-1:${account}:changeSet/cdk-deploy-change-set/*`;
    const webAcls = `arn:aws:wafv2:us-east-1:${account}:global/*`;
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: "DeployWafStack",
        actions: [
          "cloudformation:CreateChangeSet",
          "cloudformation:DescribeChangeSet",
          "cloudformation:ExecuteChangeSet",
          "cloudformation:DeleteChangeSet",
          "cloudformation:DescribeStackEvents",
          "cloudformation:GetTemplate",
          "cloudformation:GetTemplateSummary",
        ],
        resources: [wafStack, wafChangeSets],
      }),
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: "ManageWebAcl",
        actions: [
          "wafv2:CreateWebACL",
          "wafv2:UpdateWebACL",
          "wafv2:DeleteWebACL",
          "wafv2:GetWebACL",
          "wafv2:ListTagsForResource",
          "wafv2:TagResource",
          "wafv2:UntagResource",
        ],
        resources: [webAcls],
      }),
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: "ReadStackOutputs",
        actions: ["cloudformation:DescribeStacks"],
        resources: stacks,
      }),
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: "FindSubnets", // Describe* calls support no resource-level permissions
        actions: ["ec2:DescribeSubnets"],
        resources: ["*"],
        conditions: { StringEquals: { "aws:RequestedRegion": region } },
      }),
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: "RunOneOffTasks",
        actions: ["ecs:RunTask"],
        resources: [taskDefs],
        conditions: { ArnEquals: { "ecs:cluster": cluster } },
      }),
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: "WatchOneOffTasks",
        actions: ["ecs:DescribeTasks"],
        resources: [tasks],
      }),
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: "PassTaskRoles",
        actions: ["iam:PassRole"],
        resources: [taskRoles],
        conditions: { StringEquals: { "iam:PassedToService": "ecs-tasks.amazonaws.com" } },
      }),
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: "PublishWebApp",
        actions: ["s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
        resources: [site, `${site}/*`],
      }),
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: "InvalidateWebApp",
        actions: ["cloudfront:CreateInvalidation"],
        resources: [distributions],
      }),
    );
    for (const [resource, reason] of [
      [
        bootstrapRoles,
        "The CDK bootstrap roles (deploy, file/image publishing, lookup) share this naming pattern; nothing else matches it.",
      ],
      ...stacks.map((s) => [s, "Only this environment's stacks (name prefix); read-only."]),
      ["*", "ec2:DescribeSubnets has no resource-level permissions; read-only, one region."],
      [
        taskDefs,
        "Task definition revisions of this environment's compute stack; RunTask is also bound to this environment's cluster.",
      ],
      [tasks, "Tasks of this environment's cluster only."],
      [
        taskRoles,
        "Task and execution roles of this environment's compute stack, passable only to ECS tasks.",
      ],
      [`${site}/*`, "Objects of this environment's web app bucket (public static assets)."],
      [wafStack, "The WAF stack of this environment (stack ids are generated)."],
      [
        wafChangeSets,
        "Change set ids are generated by the CDK CLI; only in us-east-1 and paired with the WAF stack.",
      ],
      [
        webAcls,
        "Web ACL and managed rule group ids are generated; CLOUDFRONT scope in us-east-1 only.",
      ],
      [distributions, "Distribution ids are generated; CreateInvalidation only clears caches."],
    ]) {
      acknowledge(role, `AwsSolutions-IAM5[Resource::${resource}]`, reason as string);
    }
    new CfnOutput(this, "DeployRoleArn", { value: role.roleArn });
  }
}
