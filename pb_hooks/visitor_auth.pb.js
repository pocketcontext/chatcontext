onRecordRequestOTPRequest((e) => require(`${__hooks}/visitor_auth.js`).request(e), "users");

routerUse(new Middleware((e) => require(`${__hooks}/visitor_auth.js`).attempts(e), -1000));
// PocketBase expiry cleanup and successful consumption remove attempt counters.
onRecordAfterDeleteSuccess((e) => {
  e.next();
  for (const row of e.app.findRecordsByFilter("login_attempts", "otp = {:id}", "", 0, 0, {id: e.record.id})) e.app.delete(row);
}, "_otps");

onRecordAuthWithOTPRequest((e) => require(`${__hooks}/visitor_auth.js`).consume(e), "users");
