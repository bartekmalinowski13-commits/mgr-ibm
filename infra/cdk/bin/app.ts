#!/usr/bin/env node
import { App } from "aws-cdk-lib";
import { buildApp } from "../lib/app";

// Synth only. Deployment runs from the CI pipeline with an OIDC role, never from here.
const app = new App();
buildApp(app);
app.synth();
