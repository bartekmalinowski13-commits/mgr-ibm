import { CfnOutput, Duration, RemovalPolicy } from "aws-cdk-lib";
import * as cognito from "aws-cdk-lib/aws-cognito";
import type { Construct } from "constructs";
import { BaseStack, type BaseStackProps } from "./base-stack";
import { acknowledge } from "./nag";

/**
 * Amazon Cognito user pool (ADR-0005). The SPA signs in with the hosted login using the
 * authorization code flow with PKCE (public client, no secret) and sends the ID token
 * to the API, which verifies issuer, audience (= client id), expiry and the verified
 * e-mail. Organisations, roles and memberships live in the application database, not
 * in Cognito; per-organisation SAML/OIDC federation is added as identity providers.
 */
export class IdentityStack extends BaseStack {
  readonly userPool: cognito.UserPool;
  readonly webClient: cognito.UserPoolClient;
  readonly issuer: string;
  readonly hostedDomain: string;

  constructor(scope: Construct, id: string, props: BaseStackProps) {
    super(scope, id, props);
    const { config } = props;
    // first deployment without a custom domain: the CloudFront URL is known only afterwards;
    // tools/deploy.sh then redeploys this stack with -c bomagent:appUrl=<url>
    const appOrigin = config.appUrl ?? "https://localhost:5173";

    this.userPool = new cognito.UserPool(this, "Users", {
      userPoolName: `bomagent-${config.name}`,
      selfSignUpEnabled: true,
      signInAliases: { email: true },
      signInCaseSensitive: false,
      autoVerify: { email: true },
      keepOriginal: { email: true },
      standardAttributes: {
        email: { required: true, mutable: true },
        fullname: { required: false, mutable: true },
      },
      passwordPolicy: {
        minLength: 12,
        requireDigits: true,
        requireLowercase: true,
        requireUppercase: true,
        requireSymbols: true,
        tempPasswordValidity: Duration.days(3),
      },
      mfa: cognito.Mfa.OPTIONAL,
      mfaSecondFactor: { otp: true, sms: false },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      featurePlan: cognito.FeaturePlan.PLUS,
      standardThreatProtectionMode: cognito.StandardThreatProtectionMode.FULL_FUNCTION,
      deletionProtection: config.production,
      removalPolicy: config.production ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
    });
    acknowledge(
      this.userPool,
      "AwsSolutions-COG2",
      "MFA is optional at pool level (users enrol TOTP themselves); per-organisation enforcement for owners and admins is planned with SSO (DECISIONS_LOG) and is not yet enforced by the application. Threat protection (adaptive authentication) is on.",
    );

    this.webClient = this.userPool.addClient("Web", {
      userPoolClientName: "bomagent-web",
      generateSecret: false,
      authFlows: { userSrp: true },
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
        callbackUrls: [`${appOrigin}/auth/callback`],
        logoutUrls: [`${appOrigin}/login`],
      },
      supportedIdentityProviders: [cognito.UserPoolClientIdentityProvider.COGNITO],
      preventUserExistenceErrors: true,
      enableTokenRevocation: true,
      idTokenValidity: Duration.minutes(30),
      accessTokenValidity: Duration.minutes(30),
      refreshTokenValidity: Duration.days(7),
    });

    const domain = this.userPool.addDomain("Hosted", {
      cognitoDomain: { domainPrefix: `bomagent-${config.name}-${config.account.slice(-6)}` },
      managedLoginVersion: cognito.ManagedLoginVersion.NEWER_MANAGED_LOGIN,
    });
    this.hostedDomain = domain.baseUrl();
    this.issuer = `https://cognito-idp.${config.region}.amazonaws.com/${this.userPool.userPoolId}`;

    new CfnOutput(this, "OidcIssuer", { value: this.issuer });
    new CfnOutput(this, "OidcAudience", { value: this.webClient.userPoolClientId });
    new CfnOutput(this, "HostedLogin", { value: this.hostedDomain });
  }
}
