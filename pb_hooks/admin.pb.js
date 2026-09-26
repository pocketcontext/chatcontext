onRecordCreateRequest((e) => require(`${__hooks}/admin.js`).user(e, true), "users");
onRecordUpdateRequest((e) => require(`${__hooks}/admin.js`).user(e, false), "users");
onRecordCreateRequest((e) => require(`${__hooks}/admin.js`).member(e, "create"), "team_members");
onRecordUpdateRequest((e) => require(`${__hooks}/admin.js`).member(e, "update"), "team_members");
onRecordDeleteRequest((e) => require(`${__hooks}/admin.js`).member(e, "delete"), "team_members");
onRecordsListRequest((e) => {
  if (!(e.auth && e.auth.collection().name === "_superusers") && !require(`${__hooks}/admin.js`).admin(e.app, e.auth)) throw new ForbiddenError("Administrator access is required.");
  e.next();
}, "team_members");
onRecordViewRequest((e) => {
  if (!(e.auth && e.auth.collection().name === "_superusers") && !require(`${__hooks}/admin.js`).admin(e.app, e.auth)) throw new ForbiddenError("Administrator access is required.");
  e.next();
}, "team_members");
