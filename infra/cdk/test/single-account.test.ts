import { App } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { describe, expect, it } from "vitest";
import { buildApp } from "../lib/app";
import { IMAGE_NAMES, loadConfig } from "../lib/config";

function synthCicd(extra: Record<string, string>) {
  const app = new App({
    context: {
      "bomagent:env": "dev",
      "bomagent:account": "123456789012",
      "bomagent:githubRepository": "owner/repo",
      "@aws-cdk/core:defaultCrossStackReferences": "strong",
      ...extra,
    },
  });
  const config = loadConfig((k) => app.node.tryGetContext(k));
  return { config, cicd: Template.fromStack(buildApp(app, config).cicd) };
}

describe("single-account dev (one AWS account, images in the same account)", () => {
  const { config, cicd } = synthCicd({
    "bomagent:singleAccount": "true",
    "bomagent:monthlyBudgetUsd": "150",
    "bomagent:alarmEmail": "ops@example.com",
  });

  it("defaults the image registry to the account's own ECR", () => {
    expect(config.imageRegistry).toBe("123456789012.dkr.ecr.eu-central-1.amazonaws.com");
  });

  it("creates the image repositories: scan on push, immutable tags, lifecycle", () => {
    cicd.resourceCountIs("AWS::ECR::Repository", IMAGE_NAMES.length);
    for (const name of IMAGE_NAMES) {
      cicd.hasResourceProperties("AWS::ECR::Repository", {
        RepositoryName: name,
        ImageScanningConfiguration: { ScanOnPush: true },
        ImageTagMutability: "IMMUTABLE",
        LifecyclePolicy: Match.anyValue(),
      });
    }
  });

  it("the images role trusts only the repository's 'images' environment and may only push", () => {
    cicd.hasResourceProperties("AWS::IAM::Role", {
      RoleName: "bomagent-images-github-push",
      AssumeRolePolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Condition: Match.objectLike({
              StringEquals: Match.objectLike({
                "token.actions.githubusercontent.com:sub": "repo:owner/repo:environment:images",
              }),
            }),
          }),
        ]),
      },
    });
    const policies = JSON.stringify(cicd.findResources("AWS::IAM::Policy"));
    expect(policies).toContain("ecr:PutImage");
    expect(policies).not.toContain("ecr:DeleteRepository");
  });

  it("has a monthly cost budget with e-mail alerts", () => {
    cicd.hasResourceProperties("AWS::Budgets::Budget", {
      Budget: Match.objectLike({
        BudgetType: "COST",
        TimeUnit: "MONTHLY",
        BudgetLimit: { Amount: 150, Unit: "USD" },
      }),
      NotificationsWithSubscribers: Match.arrayWith([
        Match.objectLike({
          Subscribers: [{ SubscriptionType: "EMAIL", Address: "ops@example.com" }],
        }),
      ]),
    });
  });
});

describe("multi-account default", () => {
  it("creates no repositories and no budget unless asked", () => {
    const { cicd } = synthCicd({});
    cicd.resourceCountIs("AWS::ECR::Repository", 0);
    cicd.resourceCountIs("AWS::Budgets::Budget", 0);
  });

  it("a budget without an alarm e-mail is refused", () => {
    expect(() => synthCicd({ "bomagent:monthlyBudgetUsd": "100" })).toThrow(/alarmEmail/);
  });
});
