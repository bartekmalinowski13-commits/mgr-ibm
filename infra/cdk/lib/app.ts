import { type App, Tags, Validations } from "aws-cdk-lib";
import { AwsSolutionsChecks } from "cdk-nag";
import { ComputeStack } from "./compute-stack";
import { type EnvConfig, loadConfig } from "./config";
import { DataStack } from "./data-stack";
import { EdgeStack, WafStack } from "./edge-stack";
import { IdentityStack } from "./identity-stack";
import { NetworkStack } from "./network-stack";

export interface BomAgentStacks {
  network: NetworkStack;
  data: DataStack;
  identity: IdentityStack;
  compute: ComputeStack;
  waf: WafStack;
  edge: EdgeStack;
}

/** Builds every stack of one environment; used by bin/app.ts and the tests. */
export function buildApp(app: App, config?: EnvConfig): BomAgentStacks {
  const cfg = config ?? loadConfig((key) => app.node.tryGetContext(key));
  const env = { account: cfg.account, region: cfg.region };
  const prefix = `BomAgent-${cfg.name}`;

  const network = new NetworkStack(app, `${prefix}-Network`, { env, config: cfg });
  const data = new DataStack(app, `${prefix}-Data`, { env, config: cfg, vpc: network.vpc });
  const identity = new IdentityStack(app, `${prefix}-Identity`, { env, config: cfg });
  const compute = new ComputeStack(app, `${prefix}-Compute`, {
    env,
    config: cfg,
    vpc: network.vpc,
    logsKey: network.logsKey,
    data,
    identity,
  });

  Tags.of(app).add("project", "bomagent");
  Tags.of(app).add("environment", cfg.name);
  Tags.of(app).add("data-residency", "eu");
  Validations.of(app).addPlugins(new AwsSolutionsChecks(app, { verbose: true }));
  const waf = new WafStack(app, `${prefix}-Waf`, {
    env: { account: cfg.account, region: "us-east-1" },
    crossRegionReferences: true,
    config: cfg,
  });
  const edge = new EdgeStack(app, `${prefix}-Edge`, {
    env,
    crossRegionReferences: true,
    config: cfg,
    loadBalancer: compute.loadBalancer,
    albHttps: !!cfg.albCertificateArn,
    originSecret: compute.originSecret,
    webAclArn: waf.webAclArn,
  });
  return { network, data, identity, compute, waf, edge };
}
