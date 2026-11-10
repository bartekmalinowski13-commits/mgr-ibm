/**
 * Per-environment settings. Synth needs no AWS credentials: every account-specific
 * value comes from context (`-c key=value`) or CI variables, with harmless
 * placeholders for local synth. Nothing here is a secret.
 */
export type EnvName = "dev" | "staging" | "prod";

export interface EnvConfig {
  readonly name: EnvName;
  readonly account: string;
  /** Primary region (ADR-0002). */
  readonly region: "eu-central-1";
  /** Second EU region for backup copies. */
  readonly backupRegion: "eu-west-1";
  readonly maxAzs: number;
  readonly natGateways: number;
  readonly auroraMinAcu: number;
  readonly auroraMaxAcu: number;
  readonly auroraReaders: number;
  readonly backupRetentionDays: number;
  readonly auditRetentionDays: number;
  readonly production: boolean;
  /** CloudFront origin-facing managed prefix list in eu-central-1 (no lookups at synth). */
  readonly cloudFrontPrefixListId: string;
  /** Registry of the shared-services account (ECR) and the image tag to run. */
  readonly imageRegistry: string;
  readonly imageTag: string;
  /** Optional custom domain: certificate for CloudFront must live in us-east-1. */
  readonly domainName?: string;
  /** Public URL of the app (Cognito callback); defaults to the custom domain. */
  readonly appUrl?: string;
  readonly cloudFrontCertificateArn?: string;
  readonly albCertificateArn?: string;
  readonly alarmEmail?: string;
  readonly githubRepository: string;
  /** True when an organisation trail exists (log-archive account); else an account trail. */
  readonly organizationTrail: boolean;
}

const PLACEHOLDER_ACCOUNT = "000000000000";

const DEFAULTS: Record<
  EnvName,
  Omit<EnvConfig, "account" | "imageRegistry" | "githubRepository">
> = {
  dev: {
    name: "dev",
    region: "eu-central-1",
    backupRegion: "eu-west-1",
    maxAzs: 2,
    natGateways: 1,
    auroraMinAcu: 0.5,
    auroraMaxAcu: 4,
    auroraReaders: 0,
    backupRetentionDays: 7,
    auditRetentionDays: 30,
    production: false,
    cloudFrontPrefixListId: "pl-a3a144ca",
    imageTag: "latest",
    organizationTrail: false,
  },
  staging: {
    name: "staging",
    region: "eu-central-1",
    backupRegion: "eu-west-1",
    maxAzs: 3,
    natGateways: 1,
    auroraMinAcu: 0.5,
    auroraMaxAcu: 8,
    auroraReaders: 1,
    backupRetentionDays: 14,
    auditRetentionDays: 365,
    production: false,
    cloudFrontPrefixListId: "pl-a3a144ca",
    imageTag: "latest",
    organizationTrail: false,
  },
  prod: {
    name: "prod",
    region: "eu-central-1",
    backupRegion: "eu-west-1",
    maxAzs: 3,
    natGateways: 3,
    auroraMinAcu: 1,
    auroraMaxAcu: 32,
    auroraReaders: 1,
    backupRetentionDays: 35,
    auditRetentionDays: 3650,
    production: true,
    cloudFrontPrefixListId: "pl-a3a144ca",
    imageTag: "latest",
    organizationTrail: true,
  },
};

export function loadConfig(get: (key: string) => unknown): EnvConfig {
  const name = String(get("bomagent:env") ?? "dev") as EnvName;
  if (!(name in DEFAULTS)) throw new Error(`unknown environment ${name}`);
  const str = (key: string): string | undefined => {
    const v = get(`bomagent:${key}`);
    return v === undefined || v === "" ? undefined : String(v);
  };
  const account = str("account") ?? PLACEHOLDER_ACCOUNT;
  if (!/^\d{12}$/.test(account))
    throw new Error("bomagent:account must be a 12-digit AWS account id");
  return {
    ...DEFAULTS[name],
    account,
    imageRegistry:
      str("imageRegistry") ?? `${PLACEHOLDER_ACCOUNT}.dkr.ecr.eu-central-1.amazonaws.com`,
    imageTag: str("imageTag") ?? DEFAULTS[name].imageTag,
    domainName: str("domainName"),
    appUrl: str("appUrl") ?? (str("domainName") ? `https://${str("domainName")}` : undefined),
    cloudFrontCertificateArn: str("cloudFrontCertificateArn"),
    albCertificateArn: str("albCertificateArn"),
    alarmEmail: str("alarmEmail"),
    githubRepository: str("githubRepository") ?? "bomagent/mgr-ibm",
  };
}
