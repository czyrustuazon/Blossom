<?PHP
/*
	What this page does:
		- Shows one page of a member's pictures as a grid of thumbnails
*/

require_once("includes/global_functions.php");
require_once("includes/db_commands.php");
require_once("includes/constants.php");

session_start();
db_connect('blog');

$owner = $_GET['user'];
$page = $_GET['page'];
if ($page == '')
{
	$page = 1;
}
$start = ($page - 1) * PICTURES_PER_PAGE;

$executed = db_query("SELECT id, file_name, title FROM pictures
	WHERE owner_id = '" . $owner . "'
	ORDER BY id DESC LIMIT " . $start . ", " . PICTURES_PER_PAGE);

html_head(SITE_TITLE . ' - ' . get_username($owner));

echo "<table>";
$cell = 0;
while ($picture = mysql_fetch_array($executed))
{
	if ($cell % PICTURES_PER_ROW == 0)
	{
		echo "<tr>";
	}
	echo "<td><a href='picture.php?id=" . $picture['id'] . "'>";
	echo "<img src='" . THUMBNAIL_PIC_LOCATION . $picture['file_name'] . "' alt='" . $picture['title'] . "'>";
	echo "</a></td>";
	$cell++;
	if ($cell % PICTURES_PER_ROW == 0)
	{
		echo "</tr>";
	}
}
echo "</table>";

$total = count_pictures($owner);
echo "<p>" . $total . " pictures</p>";

db_close();
html_foot();
?>
