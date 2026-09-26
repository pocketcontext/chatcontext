migrate((app) => {
  const attempts = new Collection({name: "login_attempts", type: "base", fields: [
    {name: "otp", type: "text", required: true}, {name: "attempts", type: "number", onlyInt: true},
  ], indexes: ["CREATE UNIQUE INDEX idx_login_attempts_otp ON login_attempts (otp)"]});
  app.save(attempts);
  const admin = "@request.auth.collectionName = 'users' && @request.auth.disabled = false && @request.auth.verified = true && @collection.team_members.account ?= @request.auth.id && @collection.team_members.is_admin ?= true";
  const users = app.findCollectionByNameOrId("users");
  users.createRule = "@request.context = 'oauth2' || (" + admin + ")";
  users.updateRule = admin;
  users.manageRule = admin;
  app.save(users);
  const members = app.findCollectionByNameOrId("team_members");
  members.listRule = admin;
  members.viewRule = admin;
  members.createRule = admin;
  members.updateRule = admin;
  members.deleteRule = admin;
  app.save(members);
  const settings = app.settings();
  settings.rateLimits.enabled = true;
  settings.rateLimits.rules = [
    {label: "/api/collections/users/request-otp", audience: "", duration: 600, maxRequests: 10},
    {label: "*:auth", audience: "", duration: 60, maxRequests: 30},
    {label: "/api/", audience: "", duration: 10, maxRequests: 300},
  ];
  app.save(settings);
}, () => { throw new Error("Restore a deliberate backup to roll back identity policy."); });
