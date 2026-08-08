<?php
// Legacy login — intentionally unsafe for eval baseline.
$conn = mysql_connect('localhost', 'root', '');
mysql_select_db('app', $conn);

$user = $_POST['username'];
$pass = $_POST['password'];

$sql = "SELECT * FROM users WHERE username='$user' AND password='$pass'";
$result = mysql_query($sql, $conn);

if ($row = mysql_fetch_assoc($result)) {
    echo 'OK';
} else {
    echo 'FAIL';
}
