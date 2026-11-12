import { App } from "aws-cdk-lib";
import { buildApp } from "../lib/app";
import { loadConfig } from "../lib/config";

export function synthEnv(env: "dev" | "prod") {
  const app = new App({
    context: { "bomagent:env": env, "@aws-cdk/core:defaultCrossStackReferences": "strong" },
  });
  const config = loadConfig((k) => app.node.tryGetContext(k));
  const stacks = buildApp(app, config);
  return { app, stacks, config };
}
