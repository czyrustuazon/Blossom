<?php
/*
	What this page does:
		- Authenticates a user who has an existing account
*/

declare(strict_types=1);

require_once __DIR__ . '/includes/text_filter.php';
require_once __DIR__ . '/includes/global_functions.php';
require_once __DIR__ . '/includes/db_commands.php';
require_once __DIR__ . '/includes/constants.php';

session_start();
db_connect('user');

if (!empty($_POST['confirm_user'])) {
    $login_name = sha1(PADDED_PASSWORD_FRONT . clean_input($_POST['login_name'] ?? '') . PADDED_PASSWORD_BACK);
    $password   = sha1(PADDED_PASSWORD_FRONT . clean_input($_POST['password'] ?? '') . PADDED_PASSWORD_BACK);

    $member = db_query(
        'SELECT user_name, status, id
           FROM member_person
           JOIN member_status ON member_person.id = member_status.user_id
          WHERE login_name = ? AND hash_password = ?
          LIMIT 1',
        [$login_name, $password]
    )->fetch();

    if ($member) {
        session_regenerate_id(true);
        $_SESSION['user_id']  = (int) $member['id'];
        $_SESSION['username'] = $member['user_name'];
        $_SESSION['status']   = $member['status'];

        date_default_timezone_set(DEFAULT_TIME_ZONE);
        db_query(
            'INSERT INTO member_iphistory (last_sign_in_date, ip_address, user_id) VALUES (?, ?, ?)',
            [
                substr(date('Y-m-d H:i:s'), 0, (int) MAX_LENGTH_DATE),
                substr($_SERVER['REMOTE_ADDR'] ?? '', 0, (int) MAX_LENGTH_IP),
                (int) $member['id'],
            ]
        );

        db_close();
        redirect_to('panel.php');
    } else {
        redirect_to('message.php?code=001');
    }
}

html_head(SITE_TITLE);
?>
<form name="form1" method="post" action="login.php">
  <label>Login Name: <input type="text" name="login_name"></label><br>
  <label>Password: <input type="password" name="password"></label>
  <input type="submit" name="confirm_user" value="Submit">
</form>
<?php
html_foot();
