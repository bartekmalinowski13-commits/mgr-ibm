import { CfnOutput, Duration, RemovalPolicy } from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import type * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as s3 from "aws-cdk-lib/aws-s3";
import type * as secrets from "aws-cdk-lib/aws-secretsmanager";
import * as wafv2 from "aws-cdk-lib/aws-wafv2";
import type { Construct } from "constructs";
import { BaseStack, type BaseStackProps } from "./base-stack";
import { acknowledge } from "./nag";

/**
 * WAF for CloudFront. CloudFront is a global service and its web ACL must be created
 * in us-east-1 (the exception for global services in ADR-0002); it stores no tenant data.
 */
export class WafStack extends BaseStack {
  readonly webAclArn: string;

  constructor(scope: Construct, id: string, props: BaseStackProps) {
    super(scope, id, props);
    const managed = (name: string, priority: number) => ({
      name,
      priority,
      overrideAction: { none: {} },
      statement: { managedRuleGroupStatement: { vendorName: "AWS", name } },
      visibilityConfig: {
        cloudWatchMetricsEnabled: true,
        metricName: name,
        sampledRequestsEnabled: true,
      },
    });
    const acl = new wafv2.CfnWebACL(this, "WebAcl", {
      scope: "CLOUDFRONT",
      defaultAction: { allow: {} },
      visibilityConfig: {
        cloudWatchMetricsEnabled: true,
        metricName: `bomagent-${props.config.name}`,
        sampledRequestsEnabled: true,
      },
      rules: [
        managed("AWSManagedRulesCommonRuleSet", 1),
        managed("AWSManagedRulesKnownBadInputsRuleSet", 2),
        managed("AWSManagedRulesAmazonIpReputationList", 3),
        managed("AWSManagedRulesAnonymousIpList", 4),
        {
          name: "RateLimitPerIp",
          priority: 10,
          action: { block: {} },
          statement: { rateBasedStatement: { limit: 2000, aggregateKeyType: "IP" } },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            metricName: "RateLimitPerIp",
            sampledRequestsEnabled: true,
          },
        },
      ],
    });
    this.webAclArn = acl.attrArn;
  }
}

export interface EdgeStackProps extends BaseStackProps {
  readonly loadBalancer: elbv2.IApplicationLoadBalancer;
  readonly albHttps: boolean;
  readonly originSecret: secrets.ISecret;
  readonly webAclArn: string;
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
      minimumProtocolVersion: cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
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
