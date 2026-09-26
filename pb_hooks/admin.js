function admin(app, auth) {
  if (auth && auth.collection().name === "users") auth = app.findRecordById("users", auth.id);
  return auth && auth.collection().name === "users" && !auth.getBool("disabled") && auth.getBool("verified") &&
    app.findRecordsByFilter("team_members", "account = {:id} && is_admin = true", "", 1, 0, {id: auth.id}).length === 1;
}
function teamMember(app, auth) {
  if (auth && auth.collection().name === "users") auth = app.findRecordById("users", auth.id);
  return auth && auth.collection().name === "users" && !auth.getBool("disabled") && auth.getBool("verified") &&
    app.findRecordsByFilter("team_members", "account = {:id}", "", 1, 0, {id: auth.id}).length === 1;
}
function isSuper(e) { return e.auth && e.auth.collection().name === "_superusers"; }
function lastAdmin(app, id) {
  const rows = app.findRecordsByFilter("team_members", "is_admin = true && account != {:id} && account.disabled = false", "", 1, 0, {id});
  if (!rows.length) throw new BadRequestError("The last active administrator cannot be removed or disabled.");
}
function user(e, creating) {
  if (isSuper(e)) return e.next();
  if (creating && e.requestInfo().context === "oauth2") return e.next();
  const body = e.requestInfo().body;
  if (!creating && !admin(e.app, e.auth)) return self(e, body);
  if (!admin(e.app, e.auth)) throw new ForbiddenError("Administrator access is required.");
  const allowed = creating ? ["email", "name", "public_display_name", "password", "passwordConfirm", "verified"] : ["disabled", "public_display_name"];
  for (const key of Object.keys(body)) if (!allowed.includes(key)) throw new BadRequestError("This account field is operator-managed: " + key);
  if (creating) {
    // Administrator-created clients are ordinary identities. Membership is an
    // explicit separate operation, and no existing identity can be taken over.
    e.record.setVerified(true);
  }
  const app = e.app;
  return app.runInTransaction((tx) => {
    e.app = tx;
    try {
      if (!admin(tx, e.auth)) throw new ForbiddenError("Administrator access is required.");
      if (!creating && e.record.getBool("disabled") && admin(tx, e.record.original())) lastAdmin(tx, e.record.id);
      return e.next();
    } finally { e.app = app; }
  });
}
// Team members publish only their own alias. Visitors cannot choose a label
// that team members or other visitors would read as a company identity.
function self(e, body) {
  if (!e.auth || e.auth.id !== e.record.id || !teamMember(e.app, e.auth)) throw new ForbiddenError("Only team members can change their own public display name.");
  for (const key of Object.keys(body)) if (key !== "public_display_name") throw new BadRequestError("This account field is administrator-managed: " + key);
  const app = e.app;
  return app.runInTransaction((tx) => {
    e.app = tx;
    try {
      if (!teamMember(tx, e.auth)) throw new ForbiddenError("Only team members can change their own public display name.");
      return e.next();
    } finally { e.app = app; }
  });
}
function member(e, action) {
  if (!isSuper(e) && !admin(e.app, e.auth)) throw new ForbiddenError("Administrator access is required.");
  const app = e.app;
  return app.runInTransaction((tx) => {
    e.app = tx;
    try {
      if (!isSuper(e) && !admin(tx, e.auth)) throw new ForbiddenError("Administrator access is required.");
      if (action !== "create") {
        const old = tx.findRecordById("team_members", e.record.id);
        if (action === "update" && old.getString("account") !== e.record.getString("account")) throw new BadRequestError("Membership identity is immutable.");
        if (old.getBool("is_admin") && (action === "delete" || !e.record.getBool("is_admin"))) lastAdmin(tx, old.getString("account"));
      }
      const account = tx.findRecordById("users", e.record.getString("account"));
      if (action !== "delete" && (account.getBool("disabled") || !account.getBool("verified"))) throw new BadRequestError("Team membership requires an active verified account.");
      // Explicit operator/admin membership decisions consume JIT admission too;
      // later Google sign-in must never undo a manual revocation.
      if (!account.getBool("workspace_admitted")) {
        account.set("workspace_admitted", true);
        tx.save(account);
      }
      return e.next();
    } finally { e.app = app; }
  });
}
module.exports = {admin, user, member};
