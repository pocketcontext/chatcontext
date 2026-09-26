// Application-owned authorization. Every decision is rechecked inside the write transaction.
function rows(app, table, filter, params) {
  return app.findRecordsByFilter(table, filter, '', 0, 0, params || {});
}
function get(app, table, id) {
  try { return app.findRecordById(table, id); } catch (_) { throw new NotFoundError('Record not accessible'); }
}
function team(app, id) { return rows(app, 'team_members', 'account = {:id}', {id})[0]; }
function member(app, cid, id) { return rows(app, 'memberships', 'conversation = {:cid} && account = {:id} && active = true', {cid,id})[0]; }
function canConversation(app, c, id) {
  if (!id) return false;
  if (c.getString('kind') === 'support' && c.getString('visitor') === id) return true;
  return !!team(app,id) && (['public_channel','support'].includes(c.getString('kind')) || !!member(app,c.id,id));
}
function canMessage(app, m, id, includeDeleted) {
  return (includeDeleted || !m.getBool('deleted')) && (!m.getBool('internal') || !!team(app,id)) && canConversation(app,get(app,'conversations',m.getString('conversation')),id);
}
function denied() { throw new ForbiddenError('This operation is not permitted'); }
function invalid(message) { throw new BadRequestError(message); }
function equal(a,b,key) { return JSON.stringify(a.get(key)) === JSON.stringify(b.get(key)); }
function requireTeam(app,id) { if (!team(app,id)) denied(); }
function activeUser(app,id) { const u=get(app,'users',id); if(u.getBool('disabled') || !u.getBool('verified')) invalid('Participant must be active and verified'); return u; }
function immutable(r, old, keys) { for(const k of keys) if(!equal(r,old,k)) invalid(k+' is immutable'); }
function snapshot(r) {
  const obj=JSON.parse(JSON.stringify(r)),out={};
  for(const key of r.collection().fields.fieldNames()) out[key]=obj[key];
  return out;
}
function nextSequence(app) {
  let c=rows(app,'counters','key = "changes"')[0];
  if(!c){c=new Record(app.findCollectionByNameOrId('counters'));c.set('key','changes');}
  const n=c.getInt('value')+1;if(!Number.isSafeInteger(n))invalid('Sequence exhausted');c.set('value',n);app.save(c);return n;
}
function location(app,r) {
  const table=r.collection().name;
  if(table==='conversations')return {conversation:r.id,message:'',internal:false};
  if(table==='memberships')return {conversation:r.getString('conversation'),message:'',internal:false};
  const m=table==='messages'?r:get(app,'messages',r.getString('message'));
  return {conversation:m.getString('conversation'),message:m.id,internal:m.getBool('internal')};
}
function recordChange(app,r,actor,before,action) {
  const table=r.collection().name,loc=location(app,r);
  // Read acknowledgements are private state and must not leak through shared event/audit streams.
  if(table==='read_receipts')return;
  const change=new Record(app.findCollectionByNameOrId('changes'));
  change.set('seq',nextSequence(app));change.set('collection',table);change.set('record',r.id);change.set('action',action);
  for(const key in loc)change.set(key,loc[key]);app.save(change);
  const audit=new Record(app.findCollectionByNameOrId('audit_log'));
  audit.set('collection',table);audit.set('record',r.id);audit.set('actor',actor);audit.set('action',action);
  for(const key in loc)audit.set(key,loc[key]);audit.set('changes',{before,after:snapshot(r)});app.save(audit);
}
function serverSave(app,r,actor,action) {
  const before=r.isNew()?null:snapshot(r.original());
  r.set('revision',r.isNew()?1:r.getInt('revision')+1);
  if(r.isNew())r.set('created_by',actor);r.set('updated_by',actor);app.save(r);recordChange(app,r,actor,before,action);
}
function addMembership(app,cid,id,actor) {
  const r=new Record(app.findCollectionByNameOrId('memberships'));
  r.set('conversation',cid);r.set('account',id);r.set('active',true);serverSave(app,r,actor,'create');
}
function mentions(r) {
  const value=r.getString('mentions');if(!value || value==='null')return [];
  let v;try {v=JSON.parse(value);} catch (_) {invalid('mentions must be JSON');}if(!Array.isArray(v)||v.length>100||v.some(x=>typeof x!=='string'))invalid('mentions must be an array of at most 100 account ids');
  return Array.from(new Set(v));
}
function notify(app,m,actor) {
  const targets={};
  if(m.getString('parent')) {
    const root=get(app,'messages',m.getString('parent'));
    targets[root.getString('author')]='reply';
    for(const reply of rows(app,'messages','parent = {:id} && deleted = false',{id:root.id}))targets[reply.getString('author')]='reply';
  }
  for(const id of mentions(m))targets[id]='mention';
  for(const id in targets) {
    if(id===actor || !canMessage(app,m,id,false))continue;
    if(rows(app,'inbox','account = {:id} && message = {:message} && reason = {:reason}',{id,message:m.id,reason:targets[id]}).length)continue;
    const item=new Record(app.findCollectionByNameOrId('inbox'));item.set('account',id);item.set('message',m.id);item.set('reason',targets[id]);app.save(item);
  }
}
function validateConversation(app,r,old,fresh,id,body) {
  const kind=r.getString('kind');
  if(!fresh)immutable(r,old,['kind','visitor']);
  if(fresh) {
    if(!r.getString('title').trim())invalid('Conversation title required');
    if(kind==='support') {
      if(!team(app,id)) {if(r.getString('visitor') && r.getString('visitor')!==id)denied();r.set('visitor',id);}
      const visitor=r.getString('visitor');if(!visitor)invalid('Support requires a visitor');activeUser(app,visitor);
      if(team(app,visitor))invalid('Support owner must be an external visitor');
      if(body.participants!==undefined)invalid('Support has one visitor; participants is not accepted');
    } else {requireTeam(app,id);if(r.getString('visitor'))invalid('Only support has a visitor');}
    if(r.getString('status') && r.getString('status')!=='open')invalid('New conversations start open');
    r.set('status','open');r.set('archived',false);
  } else {
    if(!canConversation(app,old,id))denied();
    if(!team(app,id))immutable(r,old,['title','assignee','archived']);
    if(kind==='dm')immutable(r,old,['archived']);
    if(body.participants!==undefined)invalid('Participants cannot change on a conversation update');
  }
  if(kind!=='support'&&(r.getString('assignee') || r.getString('status')!=='open'))invalid('Assignment and resolution are support-only');
  if(r.getString('assignee')) {if(fresh || !equal(r,old,'assignee'))requireTeam(app,id);activeUser(app,r.getString('assignee'));requireTeam(app,r.getString('assignee'));}
  if(kind==='support'&&r.getBool('archived'))invalid('Resolve support conversations instead of archiving');
}
function validateMembership(app,r,old,fresh,id) {
  const c=get(app,'conversations',r.getString('conversation'));
  requireTeam(app,id);if(!canConversation(app,c,id))denied();
  if(!['public_channel','private_channel'].includes(c.getString('kind')))invalid('Only channels have editable membership');
  if(!fresh)immutable(r,old,['conversation','account']);
  const target=r.getString('account');activeUser(app,target);requireTeam(app,target);
  if(c.getString('kind')==='private_channel'&&!member(app,c.id,id))denied();
  if(c.getBool('archived')&&r.getBool('active'))invalid('Archived channels cannot gain members');
}
function validateMessage(app,r,old,fresh,id) {
  const c=get(app,'conversations',r.getString('conversation'));
  if(!canConversation(app,c,id))denied();
  if(c.getBool('archived'))invalid('Channel is archived');
  if(fresh) {r.set('author',id);if(r.getBool('deleted'))invalid('New messages cannot be deleted');}
  else {if(old.getString('author')!==id)denied();immutable(r,old,['conversation','parent','author','internal']);if(old.getBool('deleted'))invalid('Deleted messages are immutable');}
  if(r.getBool('internal')) {requireTeam(app,id);if(c.getString('kind')!=='support')invalid('Internal notes are support-only');}
  if(r.getString('parent')) {
    const p=get(app,'messages',r.getString('parent'));
    if(!canMessage(app,p,id,!fresh))denied();
    if(p.id===r.id||p.getString('conversation')!==c.id||p.getString('parent'))invalid('Thread parent must be a root message in this conversation');
    if(p.getBool('internal')!==r.getBool('internal'))invalid('Thread visibility must match its root');
  }
  if(r.getBool('deleted')) {r.set('body','');r.set('mentions',[]);return;}
  if(!r.getString('body').trim())invalid('Message body required');
  const ids=mentions(r);r.set('mentions',ids);
  for(const target of ids) {
    activeUser(app,target);if(!canMessage(app,r,target,false))invalid('Mention target cannot access this message');
    if(!team(app,id)) {
      requireTeam(app,target);
      if(!rows(app,'messages','conversation = {:cid} && author = {:target} && internal = false && deleted = false',{cid:c.id,target}).length)invalid('Visitors may mention only public-facing participants in their conversation');
    }
  }
}
function write(e) {
  const originalApp=e.app,r=e.record,table=r.collection().name,fresh=r.isNew(),body=e.requestInfo().body;
  const id=e.auth&&e.auth.collection().name==='users'?e.auth.id:'';
  if(!id)denied();
  originalApp.runInTransaction(app=>{e.app=app;try {
    activeUser(app,id);
    const old=fresh?null:get(app,table,r.id),before=fresh?null:snapshot(old);
    if(!fresh) {
      if(body.expected_revision===undefined||!Number.isInteger(Number(body.expected_revision)))invalid('expected_revision required');
      if(old.getInt('revision')!==Number(body.expected_revision)||old.getInt('revision')!==r.original().getInt('revision'))throw new ApiError(409,'Revision conflict',{});
      immutable(r,old,['created_by','created','author']);
    }
    const controlled=['revision','created_by','updated_by','created','updated','sha256','author'];
    for(const key of controlled)if(Object.prototype.hasOwnProperty.call(body,key))invalid(key+' is server managed');
    let participants=[];
    if(fresh && ['memberships','reactions'].includes(table) && body.active===undefined)r.set('active',true);
    if(table==='messages' && fresh && r.getString('parent') && body.internal===undefined)r.set('internal',get(app,'messages',r.getString('parent')).getBool('internal'));
    if(table==='conversations') {
      validateConversation(app,r,old,fresh,id,body);
      if(fresh&&r.getString('kind')!=='support') {
        participants=body.participants===undefined?[]:body.participants;
        if(!Array.isArray(participants)||participants.length>100||participants.some(x=>typeof x!=='string'))invalid('participants must be an array of up to 100 account ids');
        participants=Array.from(new Set([id].concat(participants)));
        if(r.getString('kind')==='dm'&&participants.length<2)invalid('A DM requires at least two participants');
        for(const target of participants){activeUser(app,target);requireTeam(app,target);}
      }
    } else if(table==='memberships')validateMembership(app,r,old,fresh,id);
    else if(table==='messages')validateMessage(app,r,old,fresh,id);
    else {
      const m=get(app,'messages',r.getString('message'));
      if(!canMessage(app,m,id,false))denied();
      if(table==='attachments') {
        if(!fresh)invalid('Original attachments are immutable');
        if(m.getString('author')!==id)denied();
        if(get(app,'conversations',m.getString('conversation')).getBool('archived'))invalid('Channel is archived');
        r.set('author',id);
      } else {
        if(fresh) {if(r.getString('account')&&r.getString('account')!==id)denied();r.set('account',id);}
        else {if(old.getString('account')!==id)denied();immutable(r,old,['message','account','emoji']);}
        if(table==='read_receipts'&&!fresh)invalid('Read receipts are immutable');
        if(table==='reactions'&&!r.getString('emoji').trim())invalid('Reaction required');
      }
    }
    r.set('revision',fresh?1:old.getInt('revision')+1);r.set('created_by',fresh?id:old.getString('created_by'));r.set('updated_by',id);
    e.next();
    if(table==='attachments') {
      const path=app.dataDir()+'/storage/'+r.collection().id+'/'+r.id+'/'+r.getString('original');
      const hash=toString($os.cmd('sha256sum',path).output()).split(' ')[0];
      if(!/^[a-f0-9]{64}$/.test(hash))invalid('Cannot verify attachment hash');
      r.set('sha256',hash);app.saveNoValidate(r);
    }
    recordChange(app,r,id,before,fresh?'create':(table==='messages'&&r.getBool('deleted')?'delete':'update'));
    if(table==='conversations'&&fresh)for(const target of participants)addMembership(app,r.id,target,id);
    if(table==='messages'&&!r.getBool('deleted')) {
      notify(app,r,id);
      const c=get(app,'conversations',r.getString('conversation'));
      if(fresh&&c.getString('kind')==='support'&&c.getString('visitor')===id&&c.getString('status')==='resolved') {c.set('status','open');serverSave(app,c,id,'reopen');}
    }
  } finally {e.app=originalApp;}});
}
function file(e) {
  if(e.record.collection().name!=='attachments')return e.next();
  let fileAuth;try {fileAuth=e.app.findAuthRecordByToken(e.requestInfo().query.token,'file');} catch (_) {throw new NotFoundError('File not accessible');}
  const id=fileAuth&&fileAuth.collection().name==='users'?fileAuth.id:'';
  if(!id)throw new NotFoundError('File not accessible');
  const u=get(e.app,'users',id),m=get(e.app,'messages',e.record.getString('message'));
  if(u.getBool('disabled')||!u.getBool('verified')||!canMessage(e.app,m,id,false))throw new NotFoundError('File not accessible');
  return e.next();
}
module.exports={write,file,team,member,canConversation,canMessage};
