<?php
/*
	What this page does:
		- Shows one page of a member's pictures as a grid of thumbnails
*/

declare(strict_types=1);

require_once __DIR__ . '/includes/global_functions.php';
require_once __DIR__ . '/includes/db_commands.php';
require_once __DIR__ . '/includes/constants.php';

session_start();
db_connect('blog');

$owner = (int) ($_GET['user'] ?? 0);
$page  = max(1, (int) ($_GET['page'] ?? 1));
$start = ($page - 1) * (int) PICTURES_PER_PAGE;

$pictures = db_query(
    'SELECT id, file_name, title FROM pictures
      WHERE owner_id = ?
      ORDER BY id DESC LIMIT ?, ?',
    [$owner, $start, (int) PICTURES_PER_PAGE]
)->fetchAll();

html_head(SITE_TITLE . ' - ' . get_username($owner));

echo '<table>';
$cell = 0;
foreach ($pictures as $picture) {
    if ($cell % (int) PICTURES_PER_ROW === 0) {
        echo '<tr>';
    }
    echo "<td><a href='picture.php?id=" . (int) $picture['id'] . "'>";
    echo "<img src='" . sanitize(THUMBNAIL_PIC_LOCATION . $picture['file_name']) . "' alt='" . sanitize($picture['title']) . "'>";
    echo '</a></td>';
    $cell++;
    if ($cell % (int) PICTURES_PER_ROW === 0) {
        echo '</tr>';
    }
}
echo '</table>';

echo '<p>' . count_pictures($owner) . ' pictures</p>';

db_close();
html_foot();
