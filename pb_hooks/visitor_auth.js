// PocketBase generates, hashes, emails, expires and consumes OTPs. An unverified
// identity shell has no session or application access until its code is proven.
function request(e) {
  const email = String(e.requestInfo().body.email || "").trim().toLowerCase();
  const matches = e.app.findRecordsByFilter("users", "email:lower = {:email}", "", 2, 0, {email});
  if (matches.length > 1) throw new BadRequestError("Unable to request a sign-in code.");
  if (matches.length) e.record = matches[0];
  if (e.record && e.record.getBool("disabled")) {
    return e.json(200, {otpId: $security.randomString(15)});
  }
  const original = e.app;
  return e.app.runInTransaction((tx) => {
    e.app = tx;
    try {
      if (!e.record) {
        e.record = new Record(tx.findCollectionByNameOrId("users"));
        e.record.setEmail(email);
        e.record.set("name", "Visitor");
        e.record.setPassword($security.randomString(48));
        e.record.setVerified(false);
        tx.save(e.record);
      }
      for (const otp of tx.findAllOTPsByRecord(e.record)) {
        for (const row of tx.findRecordsByFilter("login_attempts", "otp = {:id}", "", 0, 0, {id: otp.id})) tx.delete(row);
        tx.delete(otp);
      }
      return e.next();
    } finally { e.app = original; }
  });
}
function attempts(e) {
  if (e.request.method !== "POST" || e.request.url.path !== "/api/collections/users/auth-with-otp") return e.next();
  const id = String(e.requestInfo().body.otpId || "");
  let blocked = false;
  e.app.runInTransaction((tx) => {
    let otp;
    try { otp = tx.findOTPById(id); } catch (_) { return; }
    const rows = tx.findRecordsByFilter("login_attempts", "otp = {:id}", "", 1, 0, {id});
    const row = rows.length ? rows[0] : new Record(tx.findCollectionByNameOrId("login_attempts"));
    if (row.getInt("attempts") >= 5) { blocked = true; return; }
    row.set("otp", id); row.set("attempts", row.getInt("attempts") + 1); tx.save(row);
  });
  if (blocked) throw new TooManyRequestsError("Request a new sign-in code.");
  return e.next();
}
function consume(e) {
  const original = e.app;
  return e.app.runInTransaction((tx) => {
    e.app = tx;
    try {
      // The built-in handler validates before this hook. Recheck under the
      // writer transaction so competing attempts cannot both consume a code.
      try { tx.findOTPById(e.otp.id); } catch (_) { throw new BadRequestError("Invalid or expired OTP"); }
      return e.next();
    } finally { e.app = original; }
  });
}
module.exports = {request, attempts, consume};
