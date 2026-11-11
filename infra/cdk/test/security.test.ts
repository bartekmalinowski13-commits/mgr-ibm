import { App } from "aws-cdk-lib";
import { Annotations, Match, Template } from "aws-cdk-lib/assertions";
import { describe, expect, it } from "vitest";
import { buildApp } from "../lib/app";
import { loadConfig } from "../lib/config";
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
    expect(defs.length).toBe(7);
    for (const d of defs) {
      for (const c of d.Properties.ContainerDefinitions) {
        expect(c.User).toBe("10001:10001");
        expect(c.ReadonlyRootFilesystem).toBe(true);
      }
    }
  });

  it("only the bootstrap task sees the database master secret", () => {
    const defs = compute.findResources("AWS::ECS::TaskDefinition");
    const withAdmin = Object.entries(defs)
      .filter(([, d]) =>
        d.Properties.ContainerDefinitions.some((c: { Secrets?: { Name: string }[] }) =>
          (c.Secrets ?? []).some((s) => s.Name === "BOMAGENT_ADMIN_PASSWORD"),
        ),
      )
      .map(([id]) => id);
    expect(withAdmin).toHaveLength(1);
    expect(withAdmin[0]).toMatch(/^dbbootstrapTask/);
    const migrate = Object.entries(defs).find(([id]) => id.startsWith("migrateTask"));
    const names = migrate?.[1].Properties.ContainerDefinitions[0].Secrets.map(
      (s: { Name: string }) => s.Name,
    );
    expect(names).toEqual(["MIGRATOR_PASSWORD"]);
  });

  it("the ingest worker may only speak HTTPS and PostgreSQL, S3 only to this account", () => {
    const groups = compute.findResources("AWS::EC2::SecurityGroup");
    const ingest = Object.entries(groups).find(([id]) => id.startsWith("ingestSg"));
    const egress = ingest?.[1].Properties.SecurityGroupEgress;
    expect(egress).toEqual([
      expect.objectContaining({ CidrIp: "0.0.0.0/0", IpProtocol: "tcp", FromPort: 443 }),
      expect.objectContaining({ IpProtocol: "tcp", FromPort: 5432, ToPort: 5432 }),
    ]);
    expect(egress[1].CidrIp).toBeUndefined();
    const network = JSON.stringify(Template.fromStack(stacks.network).toJSON());
    expect(network).toContain('"aws:ResourceAccount":"000000000000"');
    expect(network).toContain("starport-layer-bucket");
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
      '"aws:RequestedRegion":["eu-central-1","eu-west-1","eu-west-3","eu-north-1","eu-south-1","eu-south-2"]',
    );
  });

  it("the API may manage identity providers of its own user pool only", () => {
    const policies = Object.values(compute.findResources("AWS::IAM::Policy"));
    const statements = policies.flatMap((p) => p.Properties.PolicyDocument.Statement);
    const sso = statements.filter(
      (s: { Sid?: string }) => s.Sid === "FederateOrganisationIdentityProviders",
    );
    expect(sso).toHaveLength(1);
    // the pool ARN imported from the identity stack, never a wildcard
    expect(JSON.stringify(sso[0].Resource)).toMatch(/BomAgent-prod-Identity.*Arn/);
    expect(JSON.stringify(sso[0].Resource)).not.toBe('"*"');
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
    expect(JSON.stringify(waf.toJSON())).not.toContain('"SampledRequestsEnabled":true');
    // no cross-region reference machinery (SSM writers, Lambdas) in us-east-1
    waf.resourceCountIs("AWS::Lambda::Function", 0);
    waf.resourceCountIs("Custom::CrossRegionExportWriter", 0);
  });

  it("WAF only counts body rules on upload endpoints, blocks them elsewhere", () => {
    const rules = Template.fromStack(stacks.waf).findResources("AWS::WAFv2::WebACL");
    const acl = Object.values(rules)[0]?.Properties;
    const common = acl.Rules.filter(
      (r: { Statement: { ManagedRuleGroupStatement?: { Name: string } } }) =>
        r.Statement.ManagedRuleGroupStatement?.Name === "AWSManagedRulesCommonRuleSet",
    );
    expect(common).toHaveLength(2);
    const [everywhere, uploads] = common;
    expect(everywhere.Statement.ManagedRuleGroupStatement.RuleActionOverrides).toBeUndefined();
    expect(
      JSON.stringify(everywhere.Statement.ManagedRuleGroupStatement.ScopeDownStatement),
    ).toContain("NotStatement");
    const overrides = uploads.Statement.ManagedRuleGroupStatement.RuleActionOverrides.map(
      (o: { Name: string }) => o.Name,
    );
    expect(overrides).toContain("SizeRestrictions_BODY");
    expect(JSON.stringify(uploads)).toContain("/v1/kb/documents");
  });

  it("a real account needs the WAF ARN, and prod needs certificates", () => {
    const build = (extra: Record<string, string>) => {
      const app = new App({
        context: {
          "@aws-cdk/core:defaultCrossStackReferences": "strong",
          "bomagent:account": "123456789012",
          "bomagent:githubRepository": "acme/app",
          ...extra,
        },
      });
      return buildApp(
        app,
        loadConfig((k) => app.node.tryGetContext(k)),
      );
    };
    const errors = (extra: Record<string, string>) =>
      Annotations.fromStack(build(extra).edge)
        .findError("*", Match.anyValue())
        .map((m) => String(m.entry.data))
        .join("\n");
    expect(errors({ "bomagent:env": "dev" })).toMatch(/webAclArn is required/);
    const acl = "arn:aws:wafv2:us-east-1:123456789012:global/webacl/x/1";
    expect(errors({ "bomagent:env": "dev", "bomagent:webAclArn": acl })).toBe("");
    expect(errors({ "bomagent:env": "prod", "bomagent:webAclArn": acl })).toMatch(
      /custom domain with certificates/,
    );
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

describe("operations", () => {
  const { stacks } = synthEnv("prod");

  it("GuardDuty scans uploads for malware and monitors ECS at runtime", () => {
    const sec = Template.fromStack(stacks.security);
    sec.hasResourceProperties("AWS::GuardDuty::MalwareProtectionPlan", {
      ProtectedResource: { S3Bucket: { BucketName: "bomagent-prod-files-000000000000" } },
    });
    expect(JSON.stringify(sec.toJSON())).toContain("ECS_FARGATE_AGENT_MANAGEMENT");
    sec.resourceCountIs("AWS::SecurityHub::Standard", 2);
    sec.resourceCountIs("AWS::AccessAnalyzer::Analyzer", 1);
  });

  it("backups are copied to a vault in eu-west-1", () => {
    expect(stacks.backupCopy.region).toBe("eu-west-1");
    const plan = JSON.stringify(
      Template.fromStack(stacks.security).findResources("AWS::Backup::BackupPlan"),
    );
    expect(plan).toContain("CopyActions");
  });

  it("the GitHub deploy role is limited to one repository environment and CDK bootstrap roles", () => {
    const cicd = JSON.stringify(Template.fromStack(stacks.cicd).toJSON());
    expect(cicd).toContain("repo:example-owner/example-repository:environment:prod");
    expect(cicd).toContain("cdk-hnb659fds-*-role-000000000000-*");
    expect(cicd).not.toContain("AdministratorAccess");
    // deploy.sh calls stay inside this environment
    expect(cicd).toContain("task-definition/BomAgentprodCompute*");
    expect(cicd).toContain("arn:aws:s3:::bomagent-prod-site-000000000000/*");
    expect(cicd).toContain('"iam:PassedToService":"ecs-tasks.amazonaws.com"');
  });

  it("a real account must name the trusted GitHub repository", () => {
    const get = (extra: Record<string, string>) => (k: string) =>
      ({ "bomagent:env": "prod", "bomagent:account": "123456789012", ...extra })[k];
    expect(() => loadConfig(get({}))).toThrow(/githubRepository is required/);
    expect(() => loadConfig(get({ "bomagent:githubRepository": "a b" }))).toThrow(/owner/);
    expect(loadConfig(get({ "bomagent:githubRepository": "acme/app" })).githubRepository).toBe(
      "acme/app",
    );
  });

  it("org-managed GuardDuty and Security Hub are not created again in the account", () => {
    const app = new App({
      context: {
        "bomagent:env": "dev",
        "@aws-cdk/core:defaultCrossStackReferences": "strong",
        "bomagent:organizationSecurityServices": "true",
      },
    });
    const sec = Template.fromStack(
      buildApp(
        app,
        loadConfig((k) => app.node.tryGetContext(k)),
      ).security,
    );
    sec.resourceCountIs("AWS::GuardDuty::Detector", 0);
    sec.resourceCountIs("AWS::SecurityHub::Hub", 0);
    sec.resourceCountIs("AWS::GuardDuty::MalwareProtectionPlan", 1);
  });

  it("an existing GitHub OIDC provider is reused instead of created", () => {
    const app = new App({
      context: {
        "bomagent:env": "dev",
        "@aws-cdk/core:defaultCrossStackReferences": "strong",
        "bomagent:githubOidcProviderArn":
          "arn:aws:iam::000000000000:oidc-provider/token.actions.githubusercontent.com",
      },
    });
    const stacks = buildApp(
      app,
      loadConfig((k) => app.node.tryGetContext(k)),
    );
    Template.fromStack(stacks.cicd).resourceCountIs("AWS::IAM::OIDCProvider", 0);
  });

  it("dead-letter queues raise alarms", () => {
    const obs = Template.fromStack(stacks.observability);
    expect(Object.keys(obs.findResources("AWS::CloudWatch::Alarm")).length).toBeGreaterThanOrEqual(
      6,
    );
    obs.hasResourceProperties("AWS::SNS::Topic", { KmsMasterKeyId: {} });
  });
});
