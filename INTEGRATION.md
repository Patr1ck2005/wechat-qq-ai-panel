# Integration contract

Access CLI: deployment.pythonExe + projectRoot/scripts/access.py. One JSON stdin request, one stdout JSON response: {"ok":true,"data":{...}} or {"ok":false,"error":{"code":"...","message":"safe text"}}. Never echo raw exceptions or secrets. No request may choose an alternative policy file.

Actions:
- catalog: trusted local setup metadata only; returns accounts [{platform,account}] and conversations [{ref,platform,account,conversation_id,title,kind}], warnings []. ref is opaque and stable.
- policy.get: returns {policy:null|{schemaVersion:1,revision:string,accounts:[{platform,account,mode:"allow"|"deny",conversations:[stable conversation_id]}]}}.
- policy.set: accepts accounts in the same shape; returns {policy:...}. No model is allowed to invoke this action.
- conversations: returns authorized conversations in the catalog shape.
- authorize: accepts refs []; returns {revision:string,allowed:refs}. Fails if any ref is unauthorized.
- messages: accepts refs [], since/until Unix seconds (fixed interval); returns {messages:[{id,ref,timestamp,sender,text,type,source}],coverage:[{ref,complete:boolean}],policy_revision:string}. Pagination is exhaustive within the interval; failures must never appear complete.
- media: accepts ref and message_id, never arbitrary filesystem paths; authorization precedes lookup.

Model interface: panel_models.create_model(settings:dict, private_root:Path) -> object with generate(system:str,text:str,on_chunk:callable,cancel:threading.Event)->str. settings contains backend="api"|"dsh", and nested api/dsh configuration. API fields: base_url,model,key_env,credential_name. DSH fields: executable,home,provider,model. Model implementation owns provider config import, credential resolution and private DSH files. No paid/live model tests.

Panel controller owns policy checks before every model request, chunking without truncation, cancellation, successful-only cursors, bounded metadata and latest results. Source references sent to models use local display labels and source IDs, never raw credential paths. Reader errors retain previous successful cursors/results.

Runtime settings: %LOCALAPPDATA%/WeChatQQAIPanel (test constructors accept isolated directories). Existing access deployment: MESSAGING_ACCESS_CONFIG or %LOCALAPPDATA%/MessagingAccess/deployment.json. Public source never hardcodes installation paths.
