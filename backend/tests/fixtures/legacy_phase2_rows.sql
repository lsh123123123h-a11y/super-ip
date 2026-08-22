INSERT INTO tenants (id, slug, name, status)
VALUES ('legacy-tenant', 'legacy-tenant', 'Legacy Tenant', 'active');

INSERT INTO users (id, external_subject, display_name, status)
VALUES ('legacy-user', 'legacy-subject', 'Legacy User', 'active');

INSERT INTO memberships (id, tenant_id, user_id, role, status)
VALUES ('legacy-membership', 'legacy-tenant', 'legacy-user', 'owner', 'active');

INSERT INTO ip_profiles (
    id, owner_id, name, promise, audience, offer, voice, evidence, boundary,
    version, is_primary
)
VALUES (
    'legacy-profile', 'legacy-subject', 'Legacy Profile', 'promise', 'audience',
    'offer', 'voice', 'evidence', 'boundary', 1, true
);

INSERT INTO campaigns (
    id, owner_id, name, goal, channels, status, target_content_count,
    metadata_payload
)
VALUES (
    'legacy-campaign', 'legacy-subject', 'Legacy Campaign', 'goal', '[]'::json,
    'active', 1, '{}'::json
);

INSERT INTO content_projects (
    id, owner_id, campaign_id, ip_profile_id, title, source_type, platform,
    brief, angle, script, status
)
VALUES (
    'legacy-content', 'legacy-subject', 'legacy-campaign', 'legacy-profile',
    'Legacy Content', 'manual', 'test', 'brief', 'angle', 'script', 'draft'
);
