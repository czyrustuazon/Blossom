<?PHP

// Undo magic quotes, then strip characters we never want in a field
function clean_input($string)
{
	if (get_magic_quotes_gpc())
	{
		$string = stripslashes($string);
	}
	return trim($string);
}

function sanitize($string)
{
	$string = str_replace(';', '&#59;', $string);		// Ending code
	$string = str_replace('`', '&#96;', $string);
	$string = str_replace('\'','&#39;', $string);		// single Quotes
	$string = str_replace('"', '&quot;', $string);		// breaking quotes
	$string = str_replace('<', '&lt;', $string);
	$string = str_replace('>', '&gt;', $string);
	$string = trim($string);

	return $string;
}

function numbers_only($string)
{
	$string = ereg_replace('[^0-9]', '', $string);
	return (int)$string;
}

// Is this a usable e-mail address?
function valid_email($email)
{
	return eregi('^[a-z0-9._-]+@[a-z0-9.-]+\.[a-z]{2,}$', $email);
}

// "red, green ,blue" -> array('red', 'green', 'blue')
function tag_list($tags)
{
	$out = array();
	$parts = split(',', $tags);
	while (list($key, $value) = each($parts))
	{
		$value = trim($value);
		if ($value != '')
		{
			$out[] = $value;
		}
	}
	return $out;
}

?>
