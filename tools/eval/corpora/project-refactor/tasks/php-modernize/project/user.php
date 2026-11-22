<?PHP
/*
	What this page does:
		- Shows a member's profile and lets the owner update their e-mail and tags
*/

require_once("includes/text_filter.php");
require_once("includes/global_functions.php");
require_once("includes/db_commands.php");
require_once("includes/constants.php");

session_start();
db_connect('user');

$user_id = numbers_only($_GET['id']);

if (!empty($_POST['save']) && $_SESSION['user_id'] == $user_id)
{
	$email = clean_input($_POST['email']);
	if (!valid_email($email))
	{
		redirect_to('message.php?code=email');
	}
	$tags = implode(',', tag_list(clean_input($_POST['tags'])));
	db_query("UPDATE member_person SET email = '$email', tags = '$tags' WHERE id = '$user_id'");
}

$executed = db_query("SELECT user_name, email, tags, about_me FROM member_person WHERE id = '$user_id'");
$member = mysql_fetch_object($executed);

html_head(SITE_TITLE . ' - ' . $member->user_name);
echo "<h1>" . sanitize($member->user_name) . "</h1>";
echo "<p>" . sanitize($member->about_me) . "</p>";
echo "<ul>";
foreach (tag_list($member->tags) as $tag)
{
	echo "<li>" . sanitize($tag) . "</li>";
}
echo "</ul>";

db_close();
html_foot();
?>
