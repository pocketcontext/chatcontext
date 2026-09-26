migrate((app) => {
  // Active team members may publish their own alias. The request hook limits
  // self-service changes to public_display_name; visitors remain excluded.
  const active = "@request.auth.collectionName = 'users' && @request.auth.disabled = false && @request.auth.verified = true";
  const admin = active + " && @collection.team_members.account ?= @request.auth.id && @collection.team_members.is_admin ?= true";
  const self = active + " && id = @request.auth.id && @collection.team_members.account ?= @request.auth.id";
  const users = app.findCollectionByNameOrId("users");
  users.updateRule = "(" + admin + ") || (" + self + ")";
  app.save(users);
}, (app) => {
  const users = app.findCollectionByNameOrId("users");
  users.updateRule = "@request.auth.collectionName = 'users' && @request.auth.disabled = false && @request.auth.verified = true && @collection.team_members.account ?= @request.auth.id && @collection.team_members.is_admin ?= true";
  app.save(users);
});
