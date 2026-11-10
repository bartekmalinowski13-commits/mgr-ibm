import { Duration, RemovalPolicy, type StackProps } from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as kms from "aws-cdk-lib/aws-kms";
import * as rds from "aws-cdk-lib/aws-rds";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secrets from "aws-cdk-lib/aws-secretsmanager";
import * as sqs from "aws-cdk-lib/aws-sqs";
import type { Construct } from "constructs";
import { BaseStack } from "./base-stack";
import type { EnvConfig } from "./config";
import { acknowledge } from "./nag";

export interface DataStackProps extends StackProps {
  readonly config: EnvConfig;
  readonly vpc: ec2.IVpc;
}

export const QUEUES = ["ingest", "runs", "kb"] as const;
export type QueueName = (typeof QUEUES)[number];
/** Database roles of ADR-0016; the application roles have no BYPASSRLS. */
export const DB_ROLES = ["bomagent_migrator", "bomagent_app", "bomagent_platform"] as const;
export type DbRole = (typeof DB_ROLES)[number];

/**
 * Tenant data: Aurora PostgreSQL 16 (pgvector + RLS), files bucket (tenant prefixes,
 * SSE-KMS), audit archive with S3 Object Lock, SQS work queues with DLQs. Everything
 * encrypted with a customer-managed key; nothing reachable from the internet.
 */
export class DataStack extends BaseStack {
  readonly dataKey: kms.Key;
  readonly cluster: rds.DatabaseCluster;
  readonly databaseSecurityGroup: ec2.SecurityGroup;
  readonly roleSecrets: Record<DbRole, secrets.Secret>;
  readonly filesBucket: s3.Bucket;
  readonly auditBucket: s3.Bucket;
  readonly accessLogsBucket: s3.Bucket;
  readonly queues: Record<QueueName, sqs.Queue>;
  readonly deadLetterQueues: Record<QueueName, sqs.Queue>;

  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);
    const { config, vpc } = props;
    const removal = config.production ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY;

    this.dataKey = new kms.Key(this, "DataKey", {
      alias: `alias/bomagent-${config.name}-data`,
      description: "Tenant data at rest: Aurora, S3, SQS, Secrets Manager",
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });

    // ---------------------------------------------------------------- database
    this.databaseSecurityGroup = new ec2.SecurityGroup(this, "DatabaseSg", {
      vpc,
      description: "Aurora: PostgreSQL from application tasks only",
      allowAllOutbound: false,
    });
    const parameters = new rds.ParameterGroup(this, "ClusterParameters", {
      engine: rds.DatabaseClusterEngine.auroraPostgres({
        version: rds.AuroraPostgresEngineVersion.VER_16_9,
      }),
      parameters: {
        "rds.force_ssl": "1",
        log_connections: "1",
        log_disconnections: "1",
        "pgaudit.log": "ddl,role",
        shared_preload_libraries: "pg_stat_statements,pgaudit",
      },
    });
    this.cluster = new rds.DatabaseCluster(this, "Database", {
      engine: rds.DatabaseClusterEngine.auroraPostgres({
        version: rds.AuroraPostgresEngineVersion.VER_16_9,
      }),
      credentials: rds.Credentials.fromGeneratedSecret("bomagent_admin", {
        encryptionKey: this.dataKey,
      }),
      defaultDatabaseName: "bomagent",
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [this.databaseSecurityGroup],
      writer: rds.ClusterInstance.serverlessV2("writer", {
        enablePerformanceInsights: true,
        performanceInsightEncryptionKey: this.dataKey,
      }),
      readers: Array.from({ length: config.auroraReaders }, (_, i) =>
        rds.ClusterInstance.serverlessV2(`reader${i + 1}`, {
          scaleWithWriter: true,
          enablePerformanceInsights: true,
          performanceInsightEncryptionKey: this.dataKey,
        }),
      ),
      serverlessV2MinCapacity: config.auroraMinAcu,
      serverlessV2MaxCapacity: config.auroraMaxAcu,
      parameterGroup: parameters,
      storageEncrypted: true,
      storageEncryptionKey: this.dataKey,
      iamAuthentication: true,
      deletionProtection: config.production,
      backup: {
        retention: Duration.days(config.backupRetentionDays),
        preferredWindow: "01:00-02:00",
      },
      cloudwatchLogsExports: ["postgresql"],
      monitoringInterval: Duration.seconds(60),
      removalPolicy: config.production ? RemovalPolicy.SNAPSHOT : RemovalPolicy.DESTROY,
    });
    this.cluster.addRotationSingleUser({ automaticallyAfter: Duration.days(30) });
    acknowledge(
      this.cluster,
      "AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole]",
      "AWS-managed service role required by RDS Enhanced Monitoring; scoped to the monitoring service principal.",
    );
    if (!config.production) {
      acknowledge(
        this.cluster,
        "AwsSolutions-RDS10",
        "Non-production environments may be torn down; prod has deletion protection.",
      );
    }

    this.roleSecrets = Object.fromEntries(
      DB_ROLES.map((role) => [
        role,
        new secrets.Secret(this, `${role}Secret`, {
          description: `Password of the PostgreSQL role ${role} (set by the migration task)`,
          encryptionKey: this.dataKey,
          generateSecretString: {
            secretStringTemplate: JSON.stringify({ username: role }),
            generateStringKey: "password",
            excludePunctuation: true,
            passwordLength: 40,
          },
          removalPolicy: removal,
        }),
      ]),
    ) as Record<DbRole, secrets.Secret>;
    for (const secret of Object.values(this.roleSecrets)) {
      acknowledge(
        secret,
        "AwsSolutions-SMG4",
        "Application role passwords are rotated by the migration task (runbook: rotate-db-role-passwords); the master secret has automatic rotation.",
      );
    }

    // ---------------------------------------------------------------- buckets
    this.accessLogsBucket = new s3.Bucket(this, "AccessLogs", {
      encryption: s3.BucketEncryption.S3_MANAGED, // S3 server access logging needs SSE-S3
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
      lifecycleRules: [{ expiration: Duration.days(config.production ? 400 : 30) }],
      removalPolicy: removal,
      autoDeleteObjects: !config.production,
    });
    acknowledge(
      this.accessLogsBucket,
      "AwsSolutions-S1",
      "This is the server access log target itself.",
    );

    this.filesBucket = new s3.Bucket(this, "Files", {
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: this.dataKey,
      bucketKeyEnabled: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      serverAccessLogsBucket: this.accessLogsBucket,
      serverAccessLogsPrefix: "files/",
      lifecycleRules: [{ noncurrentVersionExpiration: Duration.days(30) }],
      removalPolicy: removal,
      autoDeleteObjects: !config.production,
    });

    // audit export (ADR-0011). Target state: log-archive account; interim: this account
    this.auditBucket = new s3.Bucket(this, "AuditArchive", {
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: this.dataKey,
      bucketKeyEnabled: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: true,
      objectLockEnabled: true,
      objectLockDefaultRetention: config.production
        ? s3.ObjectLockRetention.compliance(Duration.days(config.auditRetentionDays))
        : s3.ObjectLockRetention.governance(Duration.days(config.auditRetentionDays)),
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      serverAccessLogsBucket: this.accessLogsBucket,
      serverAccessLogsPrefix: "audit/",
      removalPolicy: RemovalPolicy.RETAIN,
    });

    // ---------------------------------------------------------------- queues
    const visibility: Record<QueueName, Duration> = {
      ingest: Duration.minutes(10),
      runs: Duration.hours(1), // a run may take long; the API reaper handles stuck runs
      kb: Duration.minutes(15),
    };
    this.deadLetterQueues = {} as Record<QueueName, sqs.Queue>;
    this.queues = {} as Record<QueueName, sqs.Queue>;
    for (const name of QUEUES) {
      const dlq = new sqs.Queue(this, `${name}Dlq`, {
        queueName: `bomagent-${config.name}-${name}-dlq`,
        encryption: sqs.QueueEncryption.KMS,
        encryptionMasterKey: this.dataKey,
        enforceSSL: true,
        retentionPeriod: Duration.days(14),
      });
      acknowledge(dlq, "AwsSolutions-SQS3", "This queue is itself a dead-letter queue.");
      this.deadLetterQueues[name] = dlq;
      this.queues[name] = new sqs.Queue(this, `${name}Queue`, {
        queueName: `bomagent-${config.name}-${name}`,
        encryption: sqs.QueueEncryption.KMS,
        encryptionMasterKey: this.dataKey,
        enforceSSL: true,
        visibilityTimeout: visibility[name],
        retentionPeriod: Duration.days(4),
        deadLetterQueue: { queue: dlq, maxReceiveCount: 5 },
      });
    }
  }
}
