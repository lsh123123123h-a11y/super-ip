DO $$
BEGIN
    IF (SELECT tenant_id FROM ip_profiles WHERE id = 'legacy-profile') <> 'legacy-tenant'
       OR (SELECT tenant_id FROM campaigns WHERE id = 'legacy-campaign') <> 'legacy-tenant'
       OR (SELECT tenant_id FROM content_projects WHERE id = 'legacy-content') <> 'legacy-tenant' THEN
        RAISE EXCEPTION 'Phase 2 legacy tenant backfill failed';
    END IF;
    IF (SELECT role_id FROM memberships WHERE id = 'legacy-membership') <> 'role-owner' THEN
        RAISE EXCEPTION 'Phase 2 legacy role backfill failed';
    END IF;
END;
$$;
