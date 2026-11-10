import { Stack, type StackProps } from "aws-cdk-lib";
import type { Construct } from "constructs";
import type { EnvConfig } from "./config";

export interface BaseStackProps extends StackProps {
  readonly config: EnvConfig;
}

/** Stack whose availability zones come from config: synth never looks anything up in AWS. */
export class BaseStack extends Stack {
  readonly config: EnvConfig;

  constructor(scope: Construct, id: string, props: BaseStackProps) {
    super(scope, id, props);
    this.config = props.config;
  }

  override get availabilityZones(): string[] {
    const region = this.config?.region ?? "eu-central-1";
    return ["a", "b", "c"].slice(0, this.config?.maxAzs ?? 2).map((z) => `${region}${z}`);
  }
}
