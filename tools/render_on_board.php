<?php
/**
 * Render wiki text with this repository's templates on a phpBB test board
 * that has the phpBB Modders wiki extension enabled.
 *
 * Usage: php render_on_board.php BOARD_ROOT BOOTSTRAP < request.json
 *
 * BOOTSTRAP is seed-forum's bin/seed-bootstrap.php, which loads the board's
 * phpBB container from the command line. It is used in place, not copied: it
 * is GPL-licensed code and this repository is CC BY-SA.
 *
 * request.json: {"templates": {"Name": "text of Name.wiki", ...},
 *                "calls": ["{{Name|value}}", ...]}
 *
 * Every template is stored as the live version of its Template:Name page,
 * each call is rendered as an article's text is (wiki markup on while it is
 * stored, templates expanded when it is shown), and everything is rolled
 * back afterwards, so the board is left as it was.
 *
 * Output: JSON {"call": "rendered HTML", ...} on stdout. Exit status: 0 on
 * success, 1 when the board or the request cannot be used.
 */

if (PHP_SAPI !== 'cli' || $argc !== 3)
{
	fwrite(STDERR, "Usage: php render_on_board.php BOARD_ROOT BOOTSTRAP < request.json\n");
	exit(1);
}
$bootstrap = $argv[2];
if (!is_file($bootstrap))
{
	fwrite(STDERR, "No bootstrap at $bootstrap\n");
	exit(1);
}
$job = json_decode(stream_get_contents(STDIN), true);
if (!is_array($job) || !isset($job['templates'], $job['calls']) || !is_array($job['templates']) || !is_array($job['calls']))
{
	fwrite(STDERR, "The request must be JSON with \"templates\" and \"calls\"\n");
	exit(1);
}

// The bootstrap reads the board root from $argv[1]
$argv = array($argv[0], $argv[1]);
require $bootstrap;

if (!class_exists('\phpbbmodders\wiki\wiki\markup') || !$phpbb_container->get('ext.manager')->is_enabled('phpbbmodders/wiki'))
{
	fwrite(STDERR, "The phpBB Modders wiki extension is not enabled on this board\n");
	exit(1);
}
$article_table = $phpbb_container->getParameter('tables.wiki.article');
// The text renderer reads the style; a command-line run has none set up
$user->style = array('style_id' => (int) $config['default_style']);

/**
 * Parse text as a wiki article's text is parsed, with the wiki's markup on.
 *
 * @return array The stored text, its uid, bitfield and flags
 */
function wiki_store($text)
{
	$uid = $bitfield = '';
	$flags = 0;
	\phpbbmodders\wiki\wiki\markup::set_active(true);
	try
	{
		generate_text_for_storage($text, $uid, $bitfield, $flags, true, true, true);
	}
	finally
	{
		\phpbbmodders\wiki\wiki\markup::set_active(false);
	}

	return array($text, $uid, $bitfield, $flags);
}

$output = array();
$db->sql_transaction('begin');
try
{
	// Newer than any version already on the board, so these are the live ones
	$now = time() + 60;
	foreach ($job['templates'] as $name => $text)
	{
		list($stored, $uid, $bitfield) = wiki_store((string) $text);
		$db->sql_query('INSERT INTO ' . $article_table . ' ' . $db->sql_build_array('INSERT', array(
			'article_title'			=> 'Template:' . $name,
			'article_url'			=> 'Template:' . $name,
			'article_text'			=> $stored,
			'bbcode_uid'			=> $uid,
			'bbcode_bitfield'		=> $bitfield,
			'article_approved'		=> 1,
			'article_user_id'		=> (int) $user->data['user_id'],
			'article_last_edit'		=> $now,
			'article_time_created'	=> $now,
			'article_edit_reason'	=> '',
			'article_topic_id'		=> 0,
			'article_sources'		=> '',
			'article_sticky'		=> 0,
			'article_views'			=> 0,
			'article_redirect'		=> '',
			'article_description'	=> '',
			'article_toc'			=> '',
		)));
	}

	foreach ($job['calls'] as $call)
	{
		list($stored, $uid, $bitfield, $flags) = wiki_store((string) $call);
		\phpbbmodders\wiki\wiki\files::set_context('Template comparison');
		$output[$call] = generate_text_for_display($stored, $uid, $bitfield, $flags);
		\phpbbmodders\wiki\wiki\files::set_context(null);
	}
}
finally
{
	$db->sql_transaction('rollback');
}

echo json_encode($output, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES), "\n";
