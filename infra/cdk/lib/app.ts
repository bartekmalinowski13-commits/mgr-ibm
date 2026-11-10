import { type App, Tags, Validations } from "aws-cdk-lib";
import { AwsSolutionsChecks } from "cdk-nag";
import { type EnvConfig, loadConfig } from "./config";
import { DataStack } from "./data-stack";
import { IdentityStack } from "./identity-stack";
import { NetworkStack } from "./network-stack";

export interface BomAgentStacks {
  network: NetworkStack;
  data: DataStack;
  identity: IdentityStack;
}

/** Builds every stack of one environment; used by bin/app.ts and the tests. */
export function buildApp(app: App, config?: EnvConfig): BomAgentStacks {
  const cfg = config ?? loadConfig((key) => app.node.tryGetContext(key));
  const env = { account: cfg.account, region: cfg.region };
  const prefix = `BomAgent-${cfg.name}`;

  const network = new NetworkStack(app, `${prefix}-Network`, { env, config: cfg });
  const data = new DataStack(app, `${prefix}-Data`, { env, config: cfg, vpc: network.vpc });
  const identity = new IdentityStack(app, `${prefix}-Identity`, { env, config: cfg });

  Tags.of(app).add("project", "bomagent");
  Tags.of(app).add("environment", cfg.name);
  Tags.of(app).add("data-residency", "eu");
  Validations.of(app).addPlugins(new AwsSolutionsChecks(app, { verbose: true }));
  return { network, data, identity };
}
