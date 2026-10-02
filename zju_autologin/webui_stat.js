<div id="stat" style="background:#f4f7fb;padding:12px;border-radius:10px;font-size:13px;line-height:1.9">加载中…</div>
<script>
setInterval(async () => {
  try {
    const s = await (await fetch('/api/status')).json();
    const dot = s.online ? '\u{1F7E2}' : (s.ip === undefined ? '\u{26AA}' : '\u{1F534}');
    document.getElementById('stat').innerHTML =
      dot + ' <b>' + (s.online ? '在线' : '离线') + '</b>'
      + (s.latency_ms != null ? ' · ' + s.latency_ms + 'ms' : '')
      + (s.internet ? '·外网正常' : '')
      + ' · 今日掉线 ' + s.drops_today + ' 次'
      + '<br><span style="color:#777;font-size:11px">'
      + s.recent.slice(0, 3).map(e => e.time + ' ' + e.event).join('<br>')
      + '</span>';
  } catch (e) {}
}, 5000);
</script>
