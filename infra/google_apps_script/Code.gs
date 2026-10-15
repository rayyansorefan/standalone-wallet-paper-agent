// Private, free five-minute scheduler. No Gmail/Drive access and no public endpoint.
var PAPER_REPO = 'rayyansorefan/standalone-wallet-paper-agent';

function installScheduler() {
  var token = PropertiesService.getScriptProperties().getProperty('GITHUB_ACTIONS_TOKEN');
  if (!token) throw new Error('Configure GITHUB_ACTIONS_TOKEN in Script Properties first');
  var existing = ScriptApp.getProjectTriggers().filter(function(t) { return t.getHandlerFunction() === 'paperTick'; });
  if (existing.length > 1) throw new Error('Duplicate scheduler triggers require review');
  if (!existing.length) ScriptApp.newTrigger('paperTick').timeBased().everyMinutes(5).create();
  schedulerStatus();
}

function schedulerStatus() {
  console.log(JSON.stringify({
    token_configured: !!PropertiesService.getScriptProperties().getProperty('GITHUB_ACTIONS_TOKEN'),
    triggers: ScriptApp.getProjectTriggers().filter(function(t) { return t.getHandlerFunction() === 'paperTick'; }).map(function(t) { return {handler: t.getHandlerFunction(), id: t.getUniqueId()}; }),
    last_dispatch: PropertiesService.getScriptProperties().getProperty('LAST_DISPATCH')
  }));
}

function paperTick(event) {
  if (!event || !event.triggerUid) throw new Error('A genuine time-driven event is required; manual calls are rejected');
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  try {
    var now = new Date();
    var props = PropertiesService.getScriptProperties();
    var token = props.getProperty('GITHUB_ACTIONS_TOKEN');
    if (!token) throw new Error('GitHub Actions secret missing');
    var feed = UrlFetchApp.fetch('https://raw.githubusercontent.com/' + PAPER_REPO + '/main/docs/state.json?clock=' + now.getTime(), {muteHttpExceptions: true});
    if (feed.getResponseCode() !== 200) throw new Error('Cannot verify persisted account: HTTP ' + feed.getResponseCode());
    var state = JSON.parse(feed.getContentText());
    if (state.paper_only !== true || state.starting_gbp !== 2000 || !isFinite(Date.parse(state.last_run))) throw new Error('Invalid existing paper account; refusing dispatch');
    var record = {source: 'google-apps-script', trigger_uid: String(event.triggerUid), at: now.toISOString(), previous_cycle: state.last_run};
    if (now.getTime() - Date.parse(state.last_run) < 240000) {
      record.result = 'recent-cycle-skip';
    } else {
      var response = UrlFetchApp.fetch('https://api.github.com/repos/' + PAPER_REPO + '/actions/workflows/paper.yml/dispatches', {
        method: 'post', contentType: 'application/json', muteHttpExceptions: true,
        headers: {Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'},
        payload: JSON.stringify({ref: 'main', inputs: {scheduler: 'google-apps-script', scheduled_at: record.at, trigger_uid: record.trigger_uid}})
      });
      var code = response.getResponseCode();
      if (code < 200 || code >= 300) throw new Error('GitHub dispatch failed: HTTP ' + code);
      record.result = 'dispatched';
      record.http_status = code;
    }
    props.setProperty('LAST_DISPATCH', JSON.stringify(record));
    console.log(JSON.stringify(record));
  } finally { lock.releaseLock(); }
}
