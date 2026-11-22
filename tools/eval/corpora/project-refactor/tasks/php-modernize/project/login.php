<?PHP
/*
	What this page does:
		- Authenticates a user who has an existing account
*/

require_once("includes/text_filter.php");
require_once("includes/global_functions.php");
require_once("includes/db_commands.php");
require_once("includes/constants.php");

session_start();
db_connect('user');

if (!empty($_POST['confirm_user']))
{
	$login_name		= sha1(PADDED_PASSWORD_FRONT.clean_input($_POST['login_name']).PADDED_PASSWORD_BACK);
	$password		= sha1(PADDED_PASSWORD_FRONT.clean_input($_POST['password']).PADDED_PASSWORD_BACK);

	$executed = db_query("Select user_name, status, id
					from member_person, member_status
					where member_person.id = member_status.user_id
					AND login_name ='{$login_name}' and hash_password= '{$password}' LIMIT 1");

	$final_product = mysql_fetch_assoc($executed);
	if (mysql_num_rows($executed) == 1)
	{
		$_SESSION['user_id'] 	=	$final_product['id'];
		$_SESSION['username'] 	=	$final_product['user_name'];
		$_SESSION['status'] 	=	$final_product['status'];

		date_default_timezone_set(DEFAULT_TIME_ZONE);
		$date_created		= substr(date("Y-m-d H:i:s"), 0, MAX_LENGTH_DATE);
		$ip_address			= substr($_SERVER['REMOTE_ADDR'], 0, MAX_LENGTH_IP);
		$user_id			= $final_product['id'];

		db_query("INSERT INTO member_iphistory (last_sign_in_date, ip_address, user_id)
		VALUES ('{$date_created}', '{$ip_address}', '{$user_id}')");

		db_close();
		redirect_to('panel.php');
	}
	else
	{
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
<?PHP
html_foot();
?>
