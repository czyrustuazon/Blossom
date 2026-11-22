<?php
/*
	What this page does:
		- Shows a member's profile and lets the owner update their e-mail and tags
*/

declare(strict_types=1);

require_once __DIR__ . '/includes/text_filter.php';
require_once __DIR__ . '/includes/global_functions.php';
require_once __DIR__ . '/includes/db_commands.php';
require_once __DIR__ . '/includes/constants.php';

session_start();
db_connect('user');

$user_id = numbers_only($_GET['id'] ?? '');

if (!empty($_POST['save']) && ($_SESSION['user_id'] ?? null) === $user_id) {
    $email = clean_input($_POST['email'] ?? '');
    if (!valid_email($email)) {
        redirect_to('message.php?code=email');
    }
    $tags = implode(',', tag_list(clean_input($_POST['tags'] ?? '')));
    db_query('UPDATE member_person SET email = ?, tags = ? WHERE id = ?', [$email, $tags, $user_id]);
}

$member = db_query(
    'SELECT user_name, email, tags, about_me FROM member_person WHERE id = ?',
    [$user_id]
)->fetch();

if (!$member) {
    redirect_to('message.php?code=nouser');
}

html_head(SITE_TITLE . ' - ' . $member['user_name']);
echo '<h1>' . sanitize($member['user_name']) . '</h1>';
echo '<p>' . sanitize($member['about_me']) . '</p>';
echo '<ul>';
foreach (tag_list($member['tags']) as $tag) {
    echo '<li>' . sanitize($tag) . '</li>';
}
echo '</ul>';

db_close();
html_foot();
