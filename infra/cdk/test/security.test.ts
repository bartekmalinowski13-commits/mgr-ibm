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

describe("identity", () => {
  const identity = Template.fromStack(synthEnv("prod").stacks.identity);

  it("SPA client is public, code flow with PKCE, no implicit flow", () => {
    identity.hasResourceProperties("AWS::Cognito::UserPoolClient", {
      GenerateSecret: false,
      AllowedOAuthFlows: ["code"],
      PreventUserExistenceErrors: "ENABLED",
      EnableTokenRevocation: true,
    });
  });

  it("pool verifies e-mail, has a strong password policy and threat protection", () => {
    identity.hasResourceProperties("AWS::Cognito::UserPool", {
      AutoVerifiedAttributes: ["email"],
      Policies: { PasswordPolicy: { MinimumLength: 12, RequireSymbols: true } },
      UserPoolTier: "PLUS",
      DeletionProtection: "ACTIVE",
    });
  });
});

describe("compute", () => {
  const { stacks } = synthEnv("prod");
  const compute = Template.fromStack(stacks.compute);
  const services = compute.findResources("AWS::ECS::Service");

  it("every container runs as non-root with a read-only root file system", () => {
    const defs = Object.values(compute.findResources("AWS::ECS::TaskDefinition"));
    expect(defs.length).toBe(6);
    for (const d of defs) {
      for (const c of d.Properties.ContainerDefinitions) {
        expect(c.User).toBe("10001:10001");
        expect(c.ReadonlyRootFilesystem).toBe(true);
      }
    }
  });

  it("the ingest worker (untrusted files) runs in isolated subnets", () => {
    const ingest = Object.entries(services).find(([id]) => id.startsWith("ingestService"));
    expect(ingest).toBeDefined();
    const subnets = JSON.stringify(ingest?.[1].Properties.NetworkConfiguration);
    expect(subnets).toContain("isolated");
    expect(subnets).not.toContain("app");
  });

  it("the ALB accepts only CloudFront and requires the origin header", () => {
    const ingress = JSON.stringify(
      [
        ...Object.values(compute.findResources("AWS::EC2::SecurityGroup")),
        ...Object.values(compute.findResources("AWS::EC2::SecurityGroupIngress")),
      ].map((g) => g.Properties),
    );
    expect(ingress).toContain('"SourcePrefixListId":"pl-a3a144ca"');
    expect(ingress).not.toContain('"CidrIp":"0.0.0.0/0","Description":"from 0.0.0.0/0');
    expect(ingress).not.toMatch(/"IpProtocol":"tcp"[^}]*"CidrIp":"0\.0\.0\.0\/0"/);
    compute.hasResourceProperties("AWS::ElasticLoadBalancingV2::Listener", {
      DefaultActions: [{ Type: "fixed-response", FixedResponseConfig: { StatusCode: "403" } }],
    });
    compute.hasResourceProperties("AWS::ElasticLoadBalancingV2::ListenerRule", {
      Conditions: [
        { Field: "http-header", HttpHeaderConfig: { HttpHeaderName: "X-Origin-Verify" } },
      ],
    });
  });

  it("Bedrock may be called only in EU regions", () => {
    const policies = JSON.stringify(compute.findResources("AWS::IAM::Policy"));
    expect(policies).toContain(
      '"aws:RequestedRegion":["eu-central-1","eu-west-1","eu-west-3","eu-north-1"]',
    );
  });

  it("tasks may touch only tenant-prefixed objects of the files bucket", () => {
    const policies = JSON.stringify(compute.findResources("AWS::IAM::Policy"));
    expect(policies).toContain("arn:aws:s3:::bomagent-prod-files-000000000000/tenants/*");
    expect(policies).not.toContain('"s3:*"');
  });
});

describe("edge", () => {
  const { stacks } = synthEnv("prod");

  it("WAF for CloudFront lives in us-east-1 with managed rules and a rate limit", () => {
    expect(stacks.waf.region).toBe("us-east-1");
    const waf = Template.fromStack(stacks.waf);
    waf.hasResourceProperties("AWS::WAFv2::WebACL", { Scope: "CLOUDFRONT" });
    expect(JSON.stringify(waf.toJSON())).toContain("AWSManagedRulesCommonRuleSet");
    expect(JSON.stringify(waf.toJSON())).toContain("RateLimitPerIp");
  });

  it("CloudFront enforces HTTPS, sends security headers and reaches S3 only via OAC", () => {
    const edge = Template.fromStack(stacks.edge);
    edge.resourceCountIs("AWS::CloudFront::OriginAccessControl", 1);
    edge.hasResourceProperties("AWS::CloudFront::ResponseHeadersPolicy", {
      ResponseHeadersPolicyConfig: {
        SecurityHeadersConfig: {
          StrictTransportSecurity: { AccessControlMaxAgeSec: 31536000, IncludeSubdomains: true },
          FrameOptions: { FrameOption: "DENY" },
        },
      },
    });
    const dist = JSON.stringify(edge.findResources("AWS::CloudFront::Distribution"));
    expect(dist).toContain('"ViewerProtocolPolicy":"redirect-to-https"');
    expect(dist).toContain('"PathPattern":"/v1/*"');
    expect(dist).toContain("X-Origin-Verify");
    expect(dist).toContain("WebACLId");
  });
});
