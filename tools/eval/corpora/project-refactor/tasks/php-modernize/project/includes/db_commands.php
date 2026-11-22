<?PHP

$connection = '';
$result = '';

require_once ('constants.php');

// IF YOU'RE GOING TO ACCESS THE DB, YOU NEED THIS
// IT IS ALWAYS REQUIRED. ALWAYS PUT THIS BEFORE USING ANY OF THE FUNCTIONS BELOW
function db_connect($db_name = 'blog')
{
	database_name($db_name);
}
// This is used for SELECT, INSERT, UPDATE, DELETE operations
function db_query($query)
{
	global $connection;
	$results = mysql_query($query, $connection);

	if(!$results)
	{
		echo $query;
		die('database selection failed: ' . mysql_error());
	}

	return $results;
}
// This closes the database connection
function db_close()
{
	global $connection;
	mysql_close($connection);
}

function database_name($db_name)
{
	global $connection;
	switch ($db_name)
	{
		case 'blog':
			$connection = mysql_connect (DB_SERVER, DB_USER, DB_PASS);
			$selected_db = mysql_select_db(DB_NAME, $connection);
			break;

		case 'user':
			$connection = mysql_connect (DB_SERVER_USERS, DB_USER_USERS, DB_PASS_USERS);
			$selected_db = mysql_select_db(DB_NAME_USERS, $connection);
			break;
	}
}

?>
