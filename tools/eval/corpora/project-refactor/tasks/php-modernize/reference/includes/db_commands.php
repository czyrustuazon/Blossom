<?php

declare(strict_types=1);

require_once __DIR__ . '/constants.php';

/** The open connection (one per request). */
function db(?PDO $set = null): ?PDO
{
    static $pdo = null;
    if ($set !== null) {
        $pdo = $set;
    }
    return $pdo;
}

// Always call this before using any of the functions below.
function db_connect(string $db_name = 'blog'): PDO
{
    [$host, $user, $pass, $name] = match ($db_name) {
        'user' => [DB_SERVER_USERS, DB_USER_USERS, DB_PASS_USERS, DB_NAME_USERS],
        default => [DB_SERVER, DB_USER, DB_PASS, DB_NAME],
    };
    $pdo = new PDO(
        "mysql:host={$host};dbname={$name};charset=utf8mb4",
        $user,
        $pass,
        [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES => false,
        ]
    );
    db($pdo);
    return $pdo;
}

/** Run a SELECT / INSERT / UPDATE / DELETE with bound parameters. */
function db_query(string $sql, array $params = []): PDOStatement
{
    $stmt = db()->prepare($sql);
    foreach ($params as $key => $value) {
        $name = is_int($key) ? $key + 1 : $key;
        $stmt->bindValue($name, $value, is_int($value) ? PDO::PARAM_INT : PDO::PARAM_STR);
    }
    $stmt->execute();
    return $stmt;
}

function db_close(): void
{
    // PDO closes when the last reference goes away.
}
