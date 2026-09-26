onRecordCreateRequest(e=>require(`${__hooks}/chat.js`).write(e),'conversations','memberships','messages','attachments','reactions','read_receipts');
onRecordUpdateRequest(e=>require(`${__hooks}/chat.js`).write(e),'conversations','memberships','messages','attachments','reactions','read_receipts');
onRecordDeleteRequest(e=>{throw new ForbiddenError('Use archive, membership deactivation or message soft deletion; history is retained');},'conversations','memberships','messages','attachments','reactions','read_receipts','inbox','changes','audit_log','counters');
onRecordCreateRequest(e=>{throw new ForbiddenError('Server-managed collection');},'inbox','changes','audit_log','counters');
onRecordUpdateRequest(e=>{throw new ForbiddenError('Server-managed collection');},'inbox','changes','audit_log','counters');
onFileDownloadRequest(e=>require(`${__hooks}/chat.js`).file(e));
