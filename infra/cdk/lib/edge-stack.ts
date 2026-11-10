import {
  Annotations,
  BootstraplessSynthesizer,
  CfnOutput,
  Duration,
  RemovalPolicy,
} from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import type * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as s3 from "aws-cdk-lib/aws-s3";
import type * as secrets from "aws-cdk-lib/aws-secretsmanager";
import * as wafv2 from "aws-cdk-lib/aws-wafv2";
import type { Construct } from "constructs";
import { BaseStack, type BaseStackProps } from "./base-stack";
import { type EnvConfig, PLACEHOLDER_ACCOUNT } from "./config";
import { acknowledge } from "./nag";

/** Upload endpoints of the API (bomagent_api.app._upload_limit): binary bodies. */
const UPLOAD_PATHS: [string, "ENDS_WITH" | "EXACTLY"][] = [
  ["/files", "ENDS_WITH"],
  ["/evaluation", "ENDS_WITH"],
  ["/v1/kb/documents", "EXACTLY"],
];
/** Rules of the common rule set that inspect bodies: CAD/PDF files trip them by design. */
const BODY_RULES = [
  "SizeRestrictions_BODY",
  "CrossSiteScripting_BODY",
  "GenericLFI_BODY",
  "GenericRFI_BODY",
  "EC2MetaDataSSRF_BODY",
];

/**
 * WAF for CloudFront. CloudFront is a global service and its web ACL must be created
 * in us-east-1 (the exception for global services in ADR-0002); it stores no tenant data.
 * The stack needs no CDK bootstrap there (no assets): it is deployed with the CI
 * credentials and its ARN is handed to the edge stack as context (bomagent:webAclArn),
 * so nothing else has to run in us-east-1 (no cross-region reference machinery).
 */
export class WafStack extends BaseStack {
  readonly webAclArn: string;

  constructor(scope: Construct, id: string, props: BaseStackProps) {
    super(scope, id, { ...props, synthesizer: new BootstraplessSynthesizer() });
    const visibility = (metricName: string) => ({
      cloudWatchMetricsEnabled: true,
      metricName,
      // sampled requests would keep request details (headers, client IPs) in us-east-1
      sampledRequestsEnabled: false,
    });
    const upload: wafv2.CfnWebACL.StatementProperty = {
      andStatement: {
        statements: [
          {
            byteMatchStatement: {
              fieldToMatch: { method: {} },
              positionalConstraint: "EXACTLY",
              searchString: "POST",
              textTransformations: [{ priority: 0, type: "NONE" }],
            },
          },
          {
            orStatement: {
              statements: UPLOAD_PATHS.map(([path, constraint]) => ({
                byteMatchStatement: {
                  fieldToMatch: { uriPath: {} },
                  positionalConstraint: constraint,
                  searchString: path,
                  textTransformations: [{ priority: 0, type: "NONE" }],
                },
              })),
            },
          },
        ],
      },
    };
    const managed = (
      name: string,
      priority: number,
      extra: Partial<wafv2.CfnWebACL.ManagedRuleGroupStatementProperty> = {},
      ruleName = name,
    ): wafv2.CfnWebACL.RuleProperty => ({
      name: ruleName,
      priority,
      overrideAction: { none: {} },
      statement: { managedRuleGroupStatement: { vendorName: "AWS", name, ...extra } },
      visibilityConfig: visibility(ruleName),
    });
    const acl = new wafv2.CfnWebACL(this, "WebAcl", {
      scope: "CLOUDFRONT",
      defaultAction: { allow: {} },
      visibilityConfig: visibility(`bomagent-${props.config.name}`),
      rules: [
        // full common rule set everywhere except on upload bodies ...
        managed("AWSManagedRulesCommonRuleSet", 1, {
          scopeDownStatement: { notStatement: { statement: upload } },
        }),
        // ... where body rules only count: files are untrusted data handled by isolated
        // parsers and size-limited by the API, not HTML or URLs (SECURITY.md)
        managed(
          "AWSManagedRulesCommonRuleSet",
          2,
          {
            scopeDownStatement: upload,
            ruleActionOverrides: BODY_RULES.map((rule) => ({
              name: rule,
              actionToUse: { count: {} },
            })),
          },
          "AWSManagedRulesCommonRuleSet-uploads",
        ),
        managed("AWSManagedRulesKnownBadInputsRuleSet", 3),
        managed("AWSManagedRulesAmazonIpReputationList", 4),
        managed("AWSManagedRulesAnonymousIpList", 5),
        {
          name: "RateLimitPerIp",
          priority: 10,
          action: { block: {} },
          statement: { rateBasedStatement: { limit: 2000, aggregateKeyType: "IP" } },
          visibilityConfig: visibility("RateLimitPerIp"),
        },
      ],
    });
    this.webAclArn = acl.attrArn;
    new CfnOutput(this, "WebAclArn", { value: acl.attrArn });
  }
}

export function siteBucketName(config: EnvConfig): string {
  return `bomagent-${config.name}-site-${config.account}`;
}

export interface EdgeStackProps extends BaseStackProps {
  readonly loadBalancer: elbv2.IApplicationLoadBalancer;
  readonly albHttps: boolean;
  readonly originSecret: secrets.ISecret;
  /** Undefined only until the WAF stack exists: this stack then refuses to synthesize. */
  readonly webAclArn: string | undefined;
}

/**
 * CloudFront in front of everything: the SPA from a private S3 bucket (Origin Access
 * Control) and `/v1/*` to the API load balancer with the secret origin header. Security
 * headers (CSP, HSTS) are set at the edge. Same origin for SPA and API: no CORS needed.
 */
export class EdgeStack extends BaseStack {
  readonly distribution: cloudfront.Distribution;
  readonly siteBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: EdgeStackProps) {
    super(scope, id, props);
    const { config } = props;
    const removal = config.production ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY;
    if (
      config.production &&
      config.account !== PLACEHOLDER_ACCOUNT &&
      !(config.cloudFrontCertificateArn && config.domainName && props.albHttps)
    ) {
      Annotations.of(this).addError(
        "Production needs a custom domain with certificates: bomagent:domainName, bomagent:cloudFrontCertificateArn (us-east-1) and bomagent:albCertificateArn (TLS 1.2+ to viewers and HTTPS to the origin).",
      );
    }
    if (!props.webAclArn) {
      Annotations.of(this).addError(
        "bomagent:webAclArn is required: deploy the WAF stack first (tools/deploy.sh does).",
      );
    }

    const logs = new s3.Bucket(this, "EdgeLogs", {
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      objectOwnership: s3.ObjectOwnership.OBJECT_WRITER, // CloudFront standard logs need ACLs
      lifecycleRules: [{ expiration: Duration.days(config.production ? 400 : 30) }],
      removalPolicy: removal,
      autoDeleteObjects: !config.production,
    });
    acknowledge(logs, "AwsSolutions-S1", "This bucket is the log destination itself.");

    this.siteBucket = new s3.Bucket(this, "Site", {
      bucketName: siteBucketName(config), // fixed: the deploy role is scoped to it
      encryption: s3.BucketEncryption.S3_MANAGED, // public static assets of the SPA, no tenant data
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: true,
      serverAccessLogsBucket: logs,
      serverAccessLogsPrefix: "site/",
      removalPolicy: removal,
      autoDeleteObjects: !config.production,
    });

    const headers = new cloudfront.ResponseHeadersPolicy(this, "SecurityHeaders", {
      securityHeadersBehavior: {
        contentSecurityPolicy: {
          contentSecurityPolicy: [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "font-src 'self'",
            `connect-src 'self' https://cognito-idp.${config.region}.amazonaws.com https://*.auth.${config.region}.amazoncognito.com`,
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self' https://*.amazoncognito.com",
          ].join("; "),
          override: true,
        },
        strictTransportSecurity: {
          accessControlMaxAge: Duration.days(365),
          includeSubdomains: true,
          preload: true,
          override: true,
        },
        contentTypeOptions: { override: true },
        frameOptions: { frameOption: cloudfront.HeadersFrameOption.DENY, override: true },
        referrerPolicy: {
          referrerPolicy: cloudfront.HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN,
          override: true,
        },
      },
    });

    // SPA routing: paths without a file extension serve index.html (API paths never reach S3)
    const spaRewrite = new cloudfront.Function(this, "SpaRewrite", {
      runtime: cloudfront.FunctionRuntime.JS_2_0,
      code: cloudfront.FunctionCode.fromInline(
        'function handler(event){var r=event.request;if(!r.uri.includes(".")){r.uri="/index.html";}return r;}',
      ),
    });

    const api = new origins.LoadBalancerV2Origin(props.loadBalancer, {
      protocolPolicy: props.albHttps
        ? cloudfront.OriginProtocolPolicy.HTTPS_ONLY
        : cloudfront.OriginProtocolPolicy.HTTP_ONLY,
      customHeaders: { "X-Origin-Verify": props.originSecret.secretValue.unsafeUnwrap() },
      readTimeout: Duration.seconds(60),
    });

    const certificate = config.cloudFrontCertificateArn
      ? acm.Certificate.fromCertificateArn(this, "Certificate", config.cloudFrontCertificateArn)
      : undefined;
    this.distribution = new cloudfront.Distribution(this, "Distribution", {
      comment: `BOM Agent ${config.name}`,
      defaultRootObject: "index.html",
      webAclId: props.webAclArn,
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100, // edge locations in Europe and North America
      // the default *.cloudfront.net certificate has a fixed policy (TLSv1); prod needs one
      minimumProtocolVersion: certificate
        ? cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021
        : undefined,
      domainNames: config.domainName && certificate ? [config.domainName] : undefined,
      certificate,
      enableLogging: true,
      logBucket: logs,
      logFilePrefix: "cloudfront/",
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(this.siteBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        responseHeadersPolicy: headers,
        functionAssociations: [
          { function: spaRewrite, eventType: cloudfront.FunctionEventType.VIEWER_REQUEST },
        ],
      },
      additionalBehaviors: {
        "/v1/*": {
          origin: api,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
          responseHeadersPolicy: headers,
        },
      },
    });
    if (!props.webAclArn) {
      acknowledge(
        this.distribution,
        "AwsSolutions-CFR2",
        "Never deployed: without bomagent:webAclArn this stack carries an error annotation and the CLI refuses it.",
      );
    }
    if (!certificate) {
      acknowledge(
        this.distribution,
        "AwsSolutions-CFR4",
        "Without a custom domain the default *.cloudfront.net certificate is used; set bomagent:domainName and a us-east-1 certificate for TLSv1.2_2021.",
      );
    }
    if (!props.albHttps) {
      acknowledge(
        this.distribution,
        "AwsSolutions-CFR5",
        "Until an ALB certificate is configured the origin is HTTP, restricted to CloudFront addresses and a secret header; set bomagent:albCertificateArn for HTTPS to origin.",
      );
    }
    acknowledge(
      this.distribution,
      "AwsSolutions-CFR1",
      "No geo restriction: EU residency concerns where data is processed and stored (eu-central-1), not where users connect from.",
    );

    new CfnOutput(this, "Url", {
      value: config.domainName
        ? `https://${config.domainName}`
        : `https://${this.distribution.distributionDomainName}`,
    });
    new CfnOutput(this, "SiteBucket", { value: this.siteBucket.bucketName });
    new CfnOutput(this, "DistributionId", { value: this.distribution.distributionId });
  }
}
