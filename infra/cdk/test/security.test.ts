import { Template } from "aws-cdk-lib/assertions";
import { describe, expect, it } from "vitest";
import { synthEnv } from "./helpers";

describe("network and data security properties", () => {
  const dev = synthEnv("dev").stacks;
  const prod = synthEnv("prod").stacks;
  const data = Template.fromStack(prod.data);
  const network = Template.fromStack(prod.network);

  it("database is encrypted, private, TLS-only and protected in prod", () => {
    data.hasResourceProperties("AWS::RDS::DBCluster", {
      StorageEncrypted: true,
      DeletionProtection: true,
      EnableIAMDatabaseAuthentication: true,
      EngineVersion: "16.9",
    });
    data.hasResourceProperties("AWS::RDS::DBClusterParameterGroup", {
      Parameters: { "rds.force_ssl": "1" },
    });
    expect(Template.fromStack(dev.data).findResources("AWS::RDS::DBCluster")).toBeTruthy();
  });

  it("every bucket blocks public access and enforces TLS", () => {
    const buckets = data.findResources("AWS::S3::Bucket");
    for (const bucket of Object.values(buckets)) {
      expect(bucket.Properties.PublicAccessBlockConfiguration).toEqual({
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      });
    }
    const policies = Object.values(data.findResources("AWS::S3::BucketPolicy"));
    expect(policies.length).toBe(Object.keys(buckets).length);
    for (const p of policies) {
      expect(JSON.stringify(p.Properties.PolicyDocument)).toContain(
        '"aws:SecureTransport":"false"',
      );
    }
  });

  it("audit archive uses S3 Object Lock in compliance mode in prod", () => {
    data.hasResourceProperties("AWS::S3::Bucket", {
      ObjectLockEnabled: true,
      ObjectLockConfiguration: { Rule: { DefaultRetention: { Mode: "COMPLIANCE", Days: 3650 } } },
    });
  });

  it("queues are KMS-encrypted and have dead-letter queues", () => {
    const queues = Object.values(data.findResources("AWS::SQS::Queue"));
    expect(queues.length).toBe(6);
    for (const q of queues) expect(q.Properties.KmsMasterKeyId).toBeDefined();
    data.resourcePropertiesCountIs("AWS::SQS::Queue", { RedrivePolicy: { maxReceiveCount: 5 } }, 3);
  });

  it("isolated subnets have no route to the internet and AWS APIs use VPC endpoints", () => {
    const routes = Object.values(network.findResources("AWS::EC2::Route"));
    const isolatedRouteTables = Object.keys(network.findResources("AWS::EC2::RouteTable")).filter(
      (id) => id.includes("isolated"),
    );
    expect(isolatedRouteTables.length).toBeGreaterThan(0);
    for (const r of routes) {
      const table = JSON.stringify(r.Properties.RouteTableId);
      if (isolatedRouteTables.some((t) => table.includes(t)))
        throw new Error("isolated subnet has a route");
    }
    network.resourceCountIs("AWS::EC2::VPCEndpoint", 9);
    network.hasResourceProperties("AWS::EC2::VPCEndpoint", {
      ServiceName: "com.amazonaws.eu-central-1.bedrock-runtime",
    });
  });
});
