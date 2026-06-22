<?php
require_once('/usr/local/cpanel/php/WHM.php');

$status_path = '/var/cache/zahosts-health/status.json';
$collector = '/usr/local/zahosts-health/zahosts_health.py';
$refresh_output = '';

if (isset($_GET['refresh'])) {
    $lines = array();
    $code = 1;
    exec(escapeshellcmd($collector) . ' collect 2>&1', $lines, $code);
    $refresh_output = $code === 0 ? 'Refreshed successfully.' : 'Refresh failed: ' . implode("\n", $lines);
}

function h($value) {
    return htmlspecialchars((string)$value, ENT_QUOTES, 'UTF-8');
}

function read_status($path) {
    if (!file_exists($path)) {
        return null;
    }
    $raw = file_get_contents($path);
    $data = json_decode($raw, true);
    return is_array($data) ? $data : null;
}

function status_class($status) {
    if ($status === 'critical') {
        return 'zh-critical';
    }
    if ($status === 'warn') {
        return 'zh-warn';
    }
    return 'zh-ok';
}

function badge($status) {
    return '<span class="zh-badge ' . status_class($status) . '">' . h(strtoupper($status ?: 'unknown')) . '</span>';
}

function metric_card($title, $value, $detail, $status) {
    echo '<section class="zh-card">';
    echo '<div class="zh-card-top"><h3>' . h($title) . '</h3>' . badge($status) . '</div>';
    echo '<div class="zh-value">' . h($value) . '</div>';
    echo '<p>' . h($detail) . '</p>';
    echo '</section>';
}

function zh_parse_ms_event($line) {
    $line = (string)$line;
    $ev = array('time' => '', 'sender' => '', 'recipient' => '', 'status' => 'Info', 'detail' => '', 'raw' => $line);
    if (preg_match('/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(.*)$/', $line, $m)) {
        $ev['time'] = $m[1];
        $rest = $m[2];
    } else {
        $rest = $line;
    }
    if (preg_match('/(?:^|\s)(<=|=>|->|\*\*|==|>>)\s+(\S+)/', $rest, $m)) {
        $addr = trim($m[2], '<>');
        switch ($m[1]) {
            case '<=':
                $ev['status'] = 'Received';
                $ev['sender'] = $addr;
                break;
            case '=>':
            case '->':
                $ev['status'] = 'Delivered';
                $ev['recipient'] = $addr;
                break;
            case '**':
                $ev['status'] = 'Failed';
                $ev['recipient'] = $addr;
                break;
            case '==':
                $ev['status'] = 'Deferred';
                $ev['recipient'] = $addr;
                break;
            default:
                $ev['status'] = 'Info';
                $ev['recipient'] = $addr;
                break;
        }
    } elseif (preg_match('/[^\s<>@]+@[^\s<>@]+/', $rest, $m)) {
        $ev['recipient'] = $m[0];
    }
    if (preg_match('/:\s+(.+)$/', $rest, $m)) {
        $ev['detail'] = trim($m[1]);
    }
    return $ev;
}

function zh_ms_status_class($status) {
    if ($status === 'Failed') {
        return 'zh-critical';
    }
    if ($status === 'Deferred') {
        return 'zh-warn';
    }
    if ($status === 'Delivered') {
        return 'zh-ok';
    }
    return 'zh-neutral';
}

$data = read_status($status_path);

WHM::header('Zahosts Health', 0, 0);
?>
<style>
    .zh-wrap { max-width: 1280px; margin: 0 auto; padding: 18px 18px 34px; color: #1f2933; }
    .zh-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 18px; }
    .zh-head h1 { margin: 0 0 6px; font-size: 26px; font-weight: 700; }
    .zh-head p { margin: 0; color: #607080; }
    .zh-actions { display: flex; gap: 8px; align-items: center; }
    .zh-btn { display: inline-block; padding: 8px 12px; background: #0b5cab; color: #fff !important; border-radius: 4px; text-decoration: none; font-weight: 600; }
    .zh-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; margin: 16px 0 22px; }
    .zh-card { border: 1px solid #d8dee6; border-radius: 6px; padding: 14px; background: #fff; box-shadow: 0 1px 2px rgba(15, 23, 42, .04); }
    .zh-card-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
    .zh-card h3 { margin: 0; font-size: 14px; color: #334155; }
    .zh-card p { margin: 8px 0 0; min-height: 36px; color: #64748b; }
    .zh-value { margin-top: 12px; font-size: 30px; line-height: 1; font-weight: 700; color: #0f172a; }
    .zh-badge { display: inline-block; padding: 3px 7px; border-radius: 4px; font-size: 11px; font-weight: 700; }
    .zh-ok { background: #dff7e8; color: #146c2e; }
    .zh-warn { background: #fff0cc; color: #8a5a00; }
    .zh-critical { background: #ffe0e0; color: #a30000; }
    .zh-neutral { background: #eef2f7; color: #475569; }
    .zh-section { margin-top: 18px; border: 1px solid #d8dee6; border-radius: 6px; background: #fff; }
    .zh-section h2 { margin: 0; padding: 12px 14px; border-bottom: 1px solid #d8dee6; font-size: 17px; background: #f8fafc; }
    .zh-section-inner { padding: 14px; }
    .zh-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .zh-table th, .zh-table td { text-align: left; border-bottom: 1px solid #edf1f5; padding: 8px; vertical-align: top; }
    .zh-table th { color: #475569; background: #fbfdff; }
    .zh-list { margin: 0; padding-left: 18px; }
    .zh-list li { margin: 4px 0; }
    .zh-pre { white-space: pre-wrap; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; padding: 10px; max-height: 280px; overflow: auto; }
    .zh-note { margin: 12px 0; padding: 10px 12px; border-radius: 4px; background: #eff6ff; color: #1d4ed8; }
    .zh-empty { color: #64748b; }
    .zh-muted { color: #64748b; margin: 0 0 8px; font-size: 13px; }
</style>

<div class="zh-wrap">
    <div class="zh-head">
        <div>
            <h1>Zahosts Health</h1>
            <?php if ($data): ?>
                <p>Generated: <?php echo h($data['generated_at'] ?? 'unknown'); ?> | Overall <?php echo badge($data['overall_status'] ?? 'unknown'); ?></p>
            <?php else: ?>
                <p>No cached health data yet.</p>
            <?php endif; ?>
        </div>
        <div class="zh-actions">
            <a class="zh-btn" href="?refresh=1">Refresh Now</a>
        </div>
    </div>

    <?php if ($refresh_output): ?>
        <div class="zh-note"><?php echo nl2br(h($refresh_output)); ?></div>
    <?php endif; ?>

    <?php if (!$data): ?>
        <div class="zh-section"><h2>Setup</h2><div class="zh-section-inner">Run <code>/usr/local/zahosts-health/zahosts_health.py collect</code> or click Refresh Now.</div></div>
    <?php else: ?>
        <div class="zh-grid">
            <?php
            $backup_running = !empty($data['backup']['in_progress']);
            $backup_value = ($data['backup']['latest_success'] ?? false) ? 'Success' : ($backup_running ? 'Running' : 'Check');
            $backup_detail = ($backup_running ? 'Backup in progress | ' : '') . 'Dates: ' . implode(', ', $data['backup']['latest_dates'] ?? array());
            metric_card('Mail Queue', $data['mail']['queue_count'] ?? 0, 'Null-sender bounces: ' . ($data['mail']['null_sender_count'] ?? 0), $data['mail']['status'] ?? 'unknown');
            metric_card('DNSBL', strtoupper($data['dnsbl']['status'] ?? 'unknown'), 'Checked public blocklists for ' . ($data['dnsbl']['ip'] ?? ''), $data['dnsbl']['status'] ?? 'unknown');
            metric_card('Backups', $backup_value, $backup_detail, $data['backup']['status'] ?? 'unknown');
            metric_card('AutoSSL', $data['autossl']['pending_count'] ?? 0, 'Pending certificates', $data['autossl']['status'] ?? 'unknown');
            metric_card('WordPress', $data['wordpress']['total'] ?? 0, 'Plugin updates: ' . ($data['wordpress']['plugin_updates'] ?? 0) . ' | Theme updates: ' . ($data['wordpress']['theme_updates'] ?? 0), $data['wordpress']['status'] ?? 'unknown');
            metric_card('Security', $data['security']['exim_auth_fail_count'] ?? 0, 'Recent Exim auth failures', $data['security']['status'] ?? 'unknown');
            ?>
        </div>

        <div class="zh-section">
            <h2>Recommendations</h2>
            <div class="zh-section-inner">
                <?php if (!empty($data['recommendations'])): ?>
                    <ul class="zh-list">
                        <?php foreach ($data['recommendations'] as $rec): ?>
                            <li><?php echo h($rec); ?></li>
                        <?php endforeach; ?>
                    </ul>
                <?php else: ?>
                    <span class="zh-empty">No immediate action.</span>
                <?php endif; ?>
            </div>
        </div>

        <div class="zh-section">
            <h2>Email Deliverability</h2>
            <div class="zh-section-inner">
                <table class="zh-table">
                    <tr><th>Domain</th><th>User</th><th>SPF</th><th>DKIM</th><th>DMARC</th></tr>
                    <?php foreach (($data['email_auth']['records'] ?? array()) as $row): ?>
                        <tr>
                            <td><?php echo h($row['domain'] ?? ''); ?></td>
                            <td><?php echo h($row['user'] ?? ''); ?></td>
                            <td><?php echo h($row['spf'] ?? ''); ?></td>
                            <td><?php echo h($row['dkim'] ?? ''); ?></td>
                            <td><?php echo h($row['dmarc'] ?? ''); ?></td>
                        </tr>
                    <?php endforeach; ?>
                </table>
            </div>
        </div>

        <div class="zh-section">
            <h2>Microsoft Delivery Status</h2>
            <div class="zh-section-inner">
                <?php
                $ms_counts = $data['mail']['microsoft_error_counts'] ?? array();
                $ms_events = $data['mail']['microsoft_recent'] ?? array();
                if (!is_array($ms_counts)) {
                    $ms_counts = array();
                }
                if (!is_array($ms_events)) {
                    $ms_events = array();
                }
                ?>
                <p class="zh-muted">Recent Exim events for Microsoft/Outlook destinations — includes deliveries, deferrals, and failures.</p>
                <?php if (!empty($ms_counts)): ?>
                    <p>
                    <?php foreach ($ms_counts as $code => $n): ?>
                        <span class="zh-badge zh-neutral"><?php echo h($code); ?> &times;<?php echo h($n); ?></span>
                    <?php endforeach; ?>
                    </p>
                <?php endif; ?>
                <?php if (!empty($ms_events)): ?>
                    <table class="zh-table">
                        <tr><th>Time</th><th>Sender</th><th>Recipient</th><th>Status</th><th>Detail</th></tr>
                        <?php foreach ($ms_events as $ms_line): ?>
                            <?php $ev = zh_parse_ms_event($ms_line); ?>
                            <tr title="<?php echo h($ev['raw']); ?>">
                                <td><?php echo h($ev['time'] !== '' ? $ev['time'] : '—'); ?></td>
                                <td><?php echo h($ev['sender'] !== '' ? $ev['sender'] : '—'); ?></td>
                                <td><?php echo h($ev['recipient'] !== '' ? $ev['recipient'] : '—'); ?></td>
                                <td><span class="zh-badge <?php echo zh_ms_status_class($ev['status']); ?>"><?php echo h($ev['status']); ?></span></td>
                                <td><?php echo h($ev['detail'] !== '' ? $ev['detail'] : '—'); ?></td>
                            </tr>
                        <?php endforeach; ?>
                    </table>
                <?php else: ?>
                    <span class="zh-empty">No recent Microsoft delivery events.</span>
                <?php endif; ?>
            </div>
        </div>

        <div class="zh-section">
            <h2>Backups</h2>
            <div class="zh-section-inner">
                <table class="zh-table">
                    <tr><th>Enabled</th><td><?php echo h(($data['backup']['enabled'] ?? false) ? 'yes' : 'no'); ?></td></tr>
                    <tr><th>Backup directory</th><td><?php echo h($data['backup']['backup_dir'] ?? ''); ?></td></tr>
                    <tr><th>Remote destinations</th><td><?php echo h($data['backup']['remote_destinations'] ?? 0); ?></td></tr>
                    <tr><th>In progress</th><td><?php echo h(($data['backup']['in_progress'] ?? false) ? 'yes' : 'no'); ?></td></tr>
                    <tr><th>Latest log</th><td><?php echo h($data['backup']['latest_log'] ?? ''); ?></td></tr>
                </table>
                <?php if (!empty($data['backup']['active_processes'])): ?>
                    <h3>Active Backup Processes</h3>
                    <div class="zh-pre"><?php echo h(implode("\n", $data['backup']['active_processes'])); ?></div>
                <?php endif; ?>
            </div>
        </div>

        <div class="zh-section">
            <h2>WordPress Risk Dashboard</h2>
            <div class="zh-section-inner">
                <?php if (!empty($data['wordpress']['risky_sites'])): ?>
                    <table class="zh-table">
                        <tr><th>ID</th><th>Site</th><th>Version</th><th>Flags</th></tr>
                        <?php foreach ($data['wordpress']['risky_sites'] as $site): ?>
                            <tr>
                                <td><?php echo h($site['id'] ?? ''); ?></td>
                                <td><?php echo h($site['siteUrl'] ?? ''); ?></td>
                                <td><?php echo h($site['version'] ?? ''); ?></td>
                                <td><?php echo h(implode(', ', $site['flags'] ?? array())); ?></td>
                            </tr>
                        <?php endforeach; ?>
                    </table>
                <?php else: ?>
                    <span class="zh-empty">No broken, infected, unsupported, or outdated core/PHP sites detected by WP Toolkit.</span>
                <?php endif; ?>
            </div>
        </div>

        <div class="zh-section">
            <h2>Security Events Digest</h2>
            <div class="zh-section-inner">
                <h3>Top Auth Failure IPs</h3>
                <table class="zh-table">
                    <tr><th>IP</th><th>Count</th></tr>
                    <?php foreach (($data['security']['top_auth_fail_ips'] ?? array()) as $row): ?>
                        <tr><td><?php echo h($row[0] ?? ''); ?></td><td><?php echo h($row[1] ?? ''); ?></td></tr>
                    <?php endforeach; ?>
                </table>
                <h3>Top Auth Failure Subnets (/24)</h3>
                <table class="zh-table">
                    <tr><th>Subnet</th><th>Count</th></tr>
                    <?php foreach (($data['security']['top_auth_fail_subnets'] ?? array()) as $row): ?>
                        <tr><td><?php echo h($row[0] ?? ''); ?></td><td><?php echo h($row[1] ?? ''); ?></td></tr>
                    <?php endforeach; ?>
                </table>
                <h3>cPHulk Excessive Brutes</h3>
                <table class="zh-table">
                    <tr><th>IP</th><th>Country</th><th>Expires</th><th>Notes</th></tr>
                    <?php foreach (($data['security']['excessive_brutes'] ?? array()) as $row): ?>
                        <tr>
                            <td><?php echo h($row['ip'] ?? ''); ?></td>
                            <td><?php echo h($row['country_name'] ?? ''); ?></td>
                            <td><?php echo h($row['exptime'] ?? ''); ?></td>
                            <td><?php echo h($row['notes'] ?? ''); ?></td>
                        </tr>
                    <?php endforeach; ?>
                </table>
            </div>
        </div>
    <?php endif; ?>
</div>
<?php WHM::footer(); ?>
