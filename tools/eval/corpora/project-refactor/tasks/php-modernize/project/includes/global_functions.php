<?PHP
require_once("text_filter.php");
require_once("db_commands.php");
require_once("constants.php");

// A simple redirection script
function redirect_to($location = NULL)
{
	if ($location != NULL)
	{
		header("Location: {$location}");
		exit;
	}
}

// Looks up a member's display name
function get_username($user_id)
{
	$execution = db_query("SELECT user_name FROM member_person WHERE id = '" . $user_id . "' LIMIT 1");
	$row = mysql_fetch_assoc($execution);
	if (mysql_num_rows($execution) == 0)
	{
		return 'Guest';
	}
	return $row['user_name'];
}

// How many pictures a member has uploaded
function count_pictures($user_id)
{
	$execution = db_query("SELECT COUNT(*) AS total FROM pictures WHERE owner_id = '{$user_id}'");
	$row = mysql_fetch_array($execution);
	return (int)$row['total'];
}

function html_head($title)
{
	echo "<html><head><title>" . $title . "</title></head><body>";
}

function html_foot()
{
	echo "</body></html>";
}

?>
