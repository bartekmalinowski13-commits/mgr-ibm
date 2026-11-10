import { Validations } from "aws-cdk-lib";
import type { IConstruct } from "constructs";

/** Acknowledge a cdk-nag finding on a construct with a written justification. */
export function acknowledge(scope: IConstruct, id: string, reason: string): void {
  Validations.of(scope).acknowledge({ id, reason });
}
