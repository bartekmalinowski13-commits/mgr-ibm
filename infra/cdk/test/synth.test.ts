import { describe, expect, it } from "vitest";
import { synthEnv } from "./helpers";

describe.each(["dev", "prod"] as const)("%s environment", (env) => {
  it("synthesises with no unacknowledged cdk-nag (AwsSolutions) findings", () => {
    const { app } = synthEnv(env);
    expect(() => app.synth()).not.toThrow();
  }, 60_000); // cdk-nag synth takes 5-8 s on a CI runner; the default 5 s limit is flaky
});
