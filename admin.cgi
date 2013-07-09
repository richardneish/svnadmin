#!/usr/bin/perl -w
## CGI to allow people to change SVN repositories
## $Id$

use strict;
use CGI qw/:standard/;
$| = 1;

#path to repository
my $baseurl = 'http://subversion.server.org';
my $svnroot = '/srv/www/subversion';
my $websvn = 1;
my $viewcvspath = "/websvn";
my $svnpath = "/svn";
my $user_auth = "$svnroot/.htpasswd";
my $user_info = "$svnroot/.htuserinfo";
my $svnaccess_conf = "$svnroot/.htsvnaccess";
my $svnaccess_conf_perm = 0640;
my $gpgkeys = "$svnroot/.htgpgkeys";
my $gpghome = "$svnroot/.gnupg";

# path to binaries
my $gzip     = '/bin/gzip';
my $gpg      = '/usr/bin/gpg';
my $svn      = '/usr/bin/svn';
my $svnlook  = '/usr/bin/svnlook';
my $svnadmin = '/usr/bin/svnadmin';
my $htpasswd = '/usr/bin/htpasswd';

sub websvnpath($$) {
  my ($repos, $path) = @_;
  if ($websvn) {
    my $url = $viewcvspath."/listing.php?repname=$repos";
    $url .= "\&path=$path/" if $path ne "/";
    return $url;
  } else {
    return $viewcvspath."/".$repos.$path;
  }
}

#
# Redirect svnadmin to svnadmin/
# This is necessary to make repository links work.
#

if (path_info() eq "") {
    print redirect(url()."/");
    exit;
}

# Now check authorization.  The apache server already checks the
# password, we just have to check the user name.

my $curuser = $ENV{'REMOTE_USER'};
unless (defined $curuser) {
    print header(-status=>'401 Authorization Required',
		 -www_authenticate=>'Basic realm: "Subversion repository"');
    print start_html(-title => 'Authentication required!');
    print p("This server could not verify that you are authorized to access this URL. You either supplied the wrong password, or your browser doesn't understand how to supply the credentials required.");
    print end_html;
    exit 0;
}

#
# Read in current config.
#

my $action = param('action') || '';
my %htpasswd_users;
my %repositories;
my %globals;
my %user2group;


my $repos;
my $path;
if (!open(SVNACCESS, "<$svnaccess_conf")) {
    print header(-status=>'500 Internal Server Error');
    print start_html(-title => 'Subversion  eXtended Administration');
    print p("Internal Error: can't find configuration file $svnaccess_conf.");
    print end_html;
    exit 255;
}
while (<SVNACCESS>) {
    s/\#.*$//;
    next unless /\S/;
    chomp;
    s/\s+/ /g;
    
    if (/^\[([^\]]+)\]$/) {
	$path = $1;
	if ($path =~ /([^:]*):(.*)/) {
            $repos = $1;
	    $path = $2;
	    $repositories{$repos} = {} if (! defined $repositories{$repos});
	    $repositories{$repos}{$path} = {};
	} else {
	    $repos = "";
	    $globals{$path} = {};
	}
	next;
    }

    if ($_ =~ /(.*?)\s*=\s*(.*)/) {
	my $key = $1;
	my @value = split(/\s*,\s*/, $2);

	if ($repos) {
	    $repositories{$repos}{$path}{$key} = \@value;
	} else {
	    $globals{$path}{$key} = \@value;
	}
    }
}
close(SVNACCESS);

if (!open(HTPASSWD, "<$user_info")) {
    print header(-status=>'500 Internal Server Error');
    print start_html(-title => 'Subversion  eXtended Administration');
    print p("Internal Error: can't find configuration file $user_auth.");
    print end_html;
    exit 255;
}
while (<HTPASSWD>) {
    s/\#.*$//;
    next unless /\S/;
    chomp;
    s/\s+/ /g;

    my ($user, @info) = split ':', $_;
    $htpasswd_users{$user} = \@info;
}
close(HTPASSWD);


sub write_repos() {
    my $repos;
    my $path;
    my $key;
    if (!open(SVNACCESS, ">${svnaccess_conf}.new")) {
	print "Can't change access rights\n";
	return;
    }
    print SVNACCESS "#\n# Automatically generated by svnadmin.cgi\n#\n\n";
    
    foreach $path (sort keys %globals) {
	print SVNACCESS "[$path]\n";
	foreach $key (sort keys %{$globals{$path}}) {
	    print SVNACCESS "$key = ".
		join(",", @{$globals{$path}{$key}})."\n";
	}
	print SVNACCESS "\n";
    }
    foreach $repos (sort keys %repositories) {
	foreach $path (sort keys %{$repositories{$repos}}) {
	    print SVNACCESS "[$repos:$path]\n";
	    foreach $key (sort keys %{$repositories{$repos}{$path}}) {
		print SVNACCESS "$key = ".
		    join(",", @{$repositories{$repos}{$path}{$key}})."\n";
	    }
	    print SVNACCESS "\n";
	}
    }
    close(SVNACCESS);
    if (!rename("${svnaccess_conf}.new", "${svnaccess_conf}")) {
	print "Can't change access rights\n";	
	return;
    }
    chmod $svnaccess_conf_perm, "${svnaccess_conf}";
}

sub in_group($) {
    return grep(/^$curuser$/, @{$globals{"groups"}{$_[0]}}) == 1;
}

# if (path_info() =~ /^\/([a-zA-Z0-9\-][a-zA-Z0-9\.\-]*)\/svnserve\.conf$/) {
#     my $repos = $1;
#     if (in_group("$repos-admins")) {
# 	print header(-type=>'text/plain');
# 	exec ("cat", "$svnroot/$repos/conf/svnserve.conf");
# 	exit 255;
#     }
# }

#
# Backup Part
# -----------
#
# Allow to get last revision number and GPG encrypted dump of repository
#

my %gpgfpr;
sub read_gpg_keys() {
    if (!open(GPGFPR, "-|", $gpg, "--homedir", "$gpghome", "--fingerprint")) {
	return 0;
    }
    while (<GPGFPR>) {
	if ($_ =~ /Key fingerprint = ([0-9A-F ]+)/) {
	    my $fingerprint = $1;
	    $fingerprint =~ s/\s+//g;
	    my $id = lc(substr($fingerprint, -16));
	    my $uid = <GPGFPR>;
	    if ($uid =~ /^uid\s+(.*)$/) {
		$gpgfpr{$id} = $1;
	    }
	}
    }
    close(GPGFPR);
    return 1;
}

sub get_gpg_keyid($) {
    my $repos = $_[0];
    my @keys = ();

    if (!open(GPGKEYS, "<$gpgkeys")) {
        print header(-status=>'500 Internal Server Error');
	print start_html(-title => 'Subversion  eXtended Administration');
	print p("Internal Error: can't find configuration file $gpgkeys.");
	print end_html;
	exit 255;
    }
    while (<GPGKEYS>) {
	if ($_ =~ m/^$repos:([0-9a-fA-F]+(,[0-9a-fA-F]+)*)$/) {
	    @keys = split ',', $1;
	    last;
        }
    }
    close GPGKEYS;
    return @keys;
}

sub write_gpg_keyid($@) {
    my ($repos, @keys) = @_;

    if (!open(GPGKEYS, "<$gpgkeys")) {
        print header(-status=>'500 Internal Server Error');
	print start_html(-title => 'Subversion  eXtended Administration');
	print p("Internal Error: can't find configuration file $gpgkeys.");
	print end_html;
	exit 255;
    }
    if (!open(NEWGPGKEYS, ">${gpgkeys}.new")) {
	print p("Can't change gpg keys\n");
	return;
    }
    my $found = 0;
    while (<GPGKEYS>) {
	if ($_ =~ m/^$repos:([0-9a-fA-F]+(,[0-9a-fA-F]+)*)$/) {
	    print NEWGPGKEYS "$repos:".join(',', @keys)."\n";
	    $found = 1;
        } else {
	    print NEWGPGKEYS $_;
	}
    }
    print NEWGPGKEYS "$repos:".join(',', @keys)."\n" unless $found;
    close GPGKEYS;
    close NEWGPGKEYS;
    if (!rename("${gpgkeys}.new", "${gpgkeys}")) {
	print p("Can't change gpg keys\n");
	return;
    }
    chmod $svnaccess_conf_perm, "${gpgkeys}";
}

sub make_backup($$$$) {
    my ($repos, $revision, $full, $ext) = @_;
    if (!in_group("$repos-admins")
	&& ($ext ne ".gpg" || !in_group("$repos-backup"))) {
	print header(-status=>'403 Forbidden');
	print start_html(-title => 'Subversion  eXtended Administration');
	print h1("Sorry $curuser");
	print p("You're not allowed to dump repository $repos.");
	print end_html;
	exit 0;
    }

    my @gpgkeyids = ();
    if ($ext eq ".gpg") {
	@gpgkeyids = get_gpg_keyid($repos);
	if (!@gpgkeyids) {
	    print header(-status=>'404 Not Found');
	    print start_html(-title => 'Subversion  eXtended Administration');
	    print p("Dumping Repository not supported.  You need to setup the GPG keys first.");
	    print end_html;
	    exit 0;
	}
    }
    
    my @command = ($svnadmin, "dump", "-q");
    if ($revision) {
	push @command, "-r";
	push @command, "$revision";
	push @command, "--incremental" unless ($full eq "f");
    }
    push @command, "$svnroot/$repos";
    print header(-type=>'application/octetstream');
    if ($ext ne ".dump") {
	my $pid = open (SVNDUMP, "-|");
	if ($pid) {
	    # parent

	    if ($ext eq ".gpg") {
		my @param = ();
		my $keyid;
		foreach $keyid (@gpgkeyids) {
		    push @param, "-r", $keyid;
		}
		open (FILTER, "|-", $gpg, "--homedir", "$gpghome", "-e", 
		      @param);
	    } else {
		open (FILTER, "|$gzip -c");
	    }
	    my $bytesread;
	    my $buffer;
	    while ($bytesread=read(SVNDUMP,$buffer,1024)) {
		print FILTER $buffer;
	    }
	    close(FILTER);
	    exit 0;
	} else {
	    exec (@command);
	    exit 255;
	}
    } else {
	exec (@command);
	exit 255;
    }
}

if (path_info() =~ /^\/([a-zA-Z0-9\-][a-zA-Z0-9\.\-]*)\.rev$/) {
    my $repos = $1;
    if (in_group("$repos-backup") || in_group("$repos-admins")) {
	print header(-type=>'text/plain');
	# errors goto stderr, so shunt it to stdout before running htpasswd
	open STDERR, ">&STDOUT";
	exec ($svnlook, "youngest", "$svnroot/$repos");
	exit 255;
    } else {
	print header(-status=>'403 Forbidden');
        print start_html(-title => 'Subversion  eXtended Administration');
	print h1("Sorry $curuser");
	print p("You're not allowed to backup repository $repos.");
	print end_html;
	exit 0;
    }
}

#
# Repository dumps.
# This has to come first as no HTML must be printed before.
#
# DEPRECATED URL
if (path_info() =~ /^\/(([0-9]*(:[0-9]+)?)(f?)\/)?([a-zA-Z0-9\-][a-zA-Z0-9\.\-]*)\.dump(\.gz|)$/) {
    my $repos = $5;
    my $revision = $1 ? $2 : "";
    my $full = $1 ? $4 : "f";
    my $compressed = $6;
    make_backup($repos, $revision, $full, $6 ? $6 : ".dump");
}

# The preferred URL for getting a dump
#  repos(-\d+:\d+f?)?.(gz|gpg|dump)
if (path_info() =~ /^\/([a-zA-Z0-9\-][a-zA-Z0-9\.\-]*)(-([0-9]*(:[0-9]+)?)(f?))?(\.gpg|\.gz|\.dump)$/) {
    
    make_backup($1, $2 ? $3 : "", $2 ? $5 : "f", $6);
}

#
# For all other requests print HTML headers.
#
print header, start_html(-title => 'Subversion  eXtended Administration');

#
# Change passphrase
#
if ($action eq "changepw") {
    my $pw = param('passphrase') || '';
    my $vpw = param('verify') || '';
    
    print h3("Changing Passphrase");
    if (length($pw) < 6) {
	print p("Sorry, the passphrase needs to be at least 6 characters long");
    } elsif (length($pw) > 80) {
	print p("Sorry, the passphrase can only be 80 characters maximum");
    } elsif ($pw ne $vpw) {
	print p("The passphrase and the verification don't match, please try again.");
    } else {
	# ok, things are good, do the htpasswd call
	print "<pre>\n";
	
	# errors from htpasswd goto stderr, so shunt it to stdout before running htpasswd
	open STDERR, ">&STDOUT";
	
	# the braces get around a perl warning
	{ system ($htpasswd, '-b', '-m', $user_auth, $curuser, $pw); }
	print "</pre>";
    }
}

#
# Get repository from the parameters.  This can be either given by a parameter
# or as directory.
#
if (param('repos')) {
    $repos = param('repos');
} elsif (path_info() =~ /\/([a-zA-Z0-9\-][a-zA-Z0-9\.\-]*)$/) {
    $repos = $1;
} else {
    $repos = '';
}

if ($action eq "create" && in_group("admin")) {
    my $reposadmin = param('reposadmin')||'';
    print h2("Creating repository");
    if ($repos !~ /^[a-zA-Z0-9\-][a-zA-Z0-9\.\-]*$/) {
	print p("The name of the repository may only contain printable ",
		"characters.  Please try a different name");
    } elsif ($reposadmin !~ /^[a-z][a-z0-9]*$/) {
	print p("The name of the repository administrator should be a valid ",
		"login name.  Please try again.");
    } elsif (-e "$svnroot/$repos") {
	print p("A repository with that name already exists.");
    } else {
	print p("Creating repository ",code($repos),":"),"<pre>\n";
	if (mkdir("$svnroot/$repos", 0770)
	    && system($svnadmin, "create", 
		      "--fs-type", "fsfs", "$svnroot/$repos") == 0) {
	    print "</pre>";
	    print p("The repository",code($repos),
		    "was created for $reposadmin.");
	    $repositories{$repos} = { "/" => {"$reposadmin" => ["rw"]}};
	    $globals{'groups'}{"$repos-admins"} = [ $reposadmin ];
	    write_repos();
	} else {
	    print "</pre>", 
	    p("An unexpected error occured while creating repository.");
	}
    }
}

if ($action eq "adduser" && in_group("admin")) {
	my $newUser = param("newUser");
	my $fullname = param("fullname");
	my $email = param("email");
	my $pwd = param("pwd");
	my $vpwd = param("vpwd");

	if (defined $htpasswd_users{$newUser}) {
		print p("Sorry, the username already exist.");
	} elsif ($newUser !~ /^[A-Za-z0-9]+$/) {
		print p("Illegal characters in user name.");
	} elsif ($fullname !~ /^[-_A-Za-z0-9() ]+$/) {
		print p("Illegal characters in full name.");
	} elsif ($email !~ /^[-_A-Za-z0-9@.]+$/) {
		print p("Illegal characters in email address.");
	} elsif (length($newUser) < 4) {
		print p("Sorry, the username needs to be at least 4 characters long.");
  } elsif (length($pwd) < 6) {
		print p("Sorry, the passphrase needs to be at least 6 characters long");
	} elsif (length($pwd) > 80) {
		print p("Sorry, the passphrase can only be 80 characters maximum");
	} elsif ($pwd ne $vpwd) {
		print p("The passphrase and the verification don't match, please try again.");
	} else {
		# ok, things are good, do the htpasswd call
		print "<pre>\n";
		
		# errors from htpasswd goto stderr, so shunt it to stdout before running htpasswd
		open STDERR, ">&STDOUT";
		
		# the braces get around a perl warning
		{system ($htpasswd, '-b', '-m', $user_auth, $newUser, $pwd); }
		open USERINFO, ">>$user_info";
		print USERINFO "$newUser:$fullname:$email\n";
		close USERINFO;
		print "</pre>";
		$htpasswd_users{$newUser} = [ $fullname, $email ];
	}
}

if ($action eq "chgroupacl" && in_group("$repos-admins")) {
    my $needupdate = 0;
    my $numgroups = int(param("numgroups"));
    my @deletegrp = param("deletegrp");
    my $numacl = int(param("numacl"));
    my @deleteacl = param("deleteacl");

    my $i;
  groups:
    for ($i = 0; $i < $numgroups + 1; $i++) {
	my $grpname = param("grpname[$i]")||'';
	my $users = param("users[$i]") ||
	    join(',', param("l_users[$i]")) || '';
	if ($grpname eq "") {
	    # ignore added entry
	} elsif ($grpname !~ /^[a-zA-Z0-9_]+$/) {
	    print p("The name of the new group should only contain ",
		    "alphanumeric characters.  Please try again.");
	} elsif (grep /^$i$/, @deletegrp) {
	    my $j;
	    for ($j = 0; $j < $numacl; $j++) {
		my $key = param("usergroup[$j]") || '';
		if ($key eq "\@$repos-$grpname" && ! grep /^$j$/, @deleteacl) {
		    print p("Cannot delete group $repos-$grpname, ".
			    "because it is still in use.\n");
		    next groups;
		}
	    }
	    print p("Deleting group ${repos}-${grpname}.");
	    delete $globals{'groups'}{"${repos}-${grpname}"};
	    $needupdate = 1;
	} elsif ($users !~ /^[a-z][a-z0-9]*(\s*,\s*[a-z][a-z0-9]*)*$/) {
	    print p("The name of the group members of group $repos-$grpname ",
		    "should be valid login names.  Please try again.");
	} else {
	    my @value = split(/\s*,\s*/, $users);
	    my $origvalue = $globals{'groups'}{"${repos}-${grpname}"};
	    if (!defined $origvalue) {
		print p("Added group ${repos}-${grpname} with users $users");
		$globals{'groups'}{"${repos}-${grpname}"} = \@value;
		$needupdate = 1;
	    } elsif ($i == $numgroups) {
		# The expected behaviour is to add users to an
		# existing group.
		my @newvalue = @{$origvalue};
		my $user;
		foreach $user (@value) {
		    if (! grep {$_ eq $user} @newvalue) {
			print p("Added user $user to group ${repos}-${grpname}");
			push @newvalue, $user;
			$needupdate = 1;
		    }
		}
		$globals{'groups'}{"${repos}-${grpname}"} = \@newvalue;
	    } elsif (join(",", @{$origvalue}) ne join(",", @value)) {
		print p("Changed group ${repos}-${grpname} to $users");
		$globals{'groups'}{"${repos}-${grpname}"} = \@value;
		$needupdate = 1;
	    }
	}
    }

    for ($i = 0; $i < $numacl + 1; $i++) {
	my $path = param("path[$i]")||'';
	my $key = param("usergroup[$i]") || '';
	my $value = param("access[$i]")||'';
	$value = '' if $value eq '-';

	if ($key eq ""){
	    $key = undef;
	} elsif ($key =~ /^\@([a-zA-Z0-9._-]+)$/) {
	    if (! defined($globals{'groups'}{$1}) && 
		! grep /^$i$/, @deleteacl) {
		print p(escapeHTML("Unknown group: $1"));
		$key = undef;
	    }
	} elsif ($key !~ /^[a-z][a-z0-9]+$/ && $key ne '*') {
	    print p(escapeHTML("Invalid login name: $key"));
	    $key = undef;
	}

	if (!defined $key) {
	    # error printed above
	} elsif ($value !~ /^(rw?)?$/
		 || $path !~ /^[!-Z^-~]+$/) {
	    print p(escapeHTML("Invalid values: $path $key $value"));
	} else {
	    if (grep /^$i$/, @deleteacl) {
		delete $repositories{$repos}{$path}{$key};
		$needupdate = 1;
		if (scalar(keys %{$repositories{$repos}{$path}}) == 0) {
		    delete $repositories{$repos}{$path};
		    print p("Delete a path: $repos:$path $key");
		} else {
		    print p("Delete a user: $repos:$path $key");
		}
	    } elsif (!defined $repositories{$repos}{$path}) {
		$repositories{$repos}{$path} = {$key => [$value]};
		print p("Creating a path: $repos:$path $key $value");
		$needupdate = 1;
	    } elsif (!defined $repositories{$repos}{$path}{$key}) {
		print p("Creating a user: $repos:$path $key $value");
		$repositories{$repos}{$path}{$key} = [$value];
		$needupdate = 1;
	    } elsif (join(",", @{$repositories{$repos}{$path}{$key}}) 
		     ne $value) {
		$repositories{$repos}{$path}{$key} = [$value];
		print p("Changing access entry: $repos:$path $key $value");
		$needupdate = 1;
	    }
	}
    }
    write_repos() if ($needupdate);
    if (param("gpgaddkey") || param("gpgdelkey")) {
	my @gpgkeyids = get_gpg_keyid($repos);
	my $key = param("gpgaddkey");
	if ($key =~ /^[0-9a-f]+$/) {
	    if (!grep {$_ eq $key} @gpgkeyids) {
		print p("Adding gpg key $key to backup");
		push @gpgkeyids, $key;
	    }
	} elsif ($key) {
	    print p(escapeHTML("Invalid key: $key"));
	}
	foreach $key (param("gpgdelkey")) {
	    if ($key =~ /^[0-9a-f]+$/) {
		print p("Removing gpg key $key for backup");
		@gpgkeyids = grep {$_ ne $key} @gpgkeyids;
	    } elsif ($key) {
		print p(escapeHTML("Invalid key: $key"));
	    }
	}
	write_gpg_keyid($repos, @gpgkeyids);
    }

    my $gpgkeyfile = upload('gpgkeyfile');
    if (defined $gpgkeyfile) {
	print p("Importing GPG key:");
	print "<pre>\n";
	
	# errors from GPG goto stderr, so shunt it to stdout before running htpasswd
	open STDERR, ">&STDOUT";
	
	# upload a new public key
	open (GPG, "|-", $gpg, "--homedir", "$gpghome", "--import");
	my $bytesread;
	my $buffer;
	while ($bytesread=read($gpgkeyfile,$buffer,1024)) {
	    print GPG $buffer;
	}
	close(GPG);
	close($gpgkeyfile);

	print "</pre>";
    }
}

if ($action eq "load" && in_group("$repos-admins")) {
    my $dumpfile = upload('dumpfile');
    my $dumpsubdir = param('dumpsubdir')||'';
    print h2(escapeHTML("Loading repository dump file into $repos:$dumpsubdir"));
    if (!defined $dumpfile) {
	print p("No file was uploaded (",
		escapeHTML($dumpfile),",",
		escapeHTML(param("dumpfile")),",",
		escapeHTML(cgi_error).")???");
    } else {
	my $result;
	my $dumpfilename = param('dumpfile');
	my @command = ($svnadmin, "load");
	if ($dumpsubdir) {
	    push @command, "--parent-dir", "$dumpsubdir";
	}
	push @command,"$svnroot/$repos";
	my $pid = open (SVNDUMP, "-|");
	if (!defined $pid) {
	    print p(escapeHTML("Cannot fork: $!"));
	} elsif ($pid) { 
	    # parent
	    print "<pre>\n";
	    while (<SVNDUMP>) {
		print escapeHTML($_);
	    }
	    print "</pre>\n";
	    close(SVNDUMP);
	} else {
	    open (STDIN, "<&=", $dumpfile);
	    open (STDERR, ">&STDOUT");
	    if ($dumpfilename =~ /\.gz$/) {
		open (STDIN, "$gzip -dc|");
	    }
	    exec @command;
	    exit 255;
	}
    }
}

# if ($action eq "loadconf" && in_group("$repos-admins")) {
#     my $conffile = upload('conffile');
#     my $conffilename = param('conffile');
#     print h2(escapeHTML("Loading config file into $repos"));
#     if (!defined $conffile) {
# 	print p("No file was uploaded (",
# 		escapeHTML($conffilename),",",
# 		escapeHTML(param("conffile")),",",
# 		escapeHTML(cgi_error).")???");
#     } else {
# 	my $result;
# 	open CONFFILE, ">$svnroot/$repos/conf/svnserve.conf";
# 	print "<pre>\n";
# 	while (<$conffile>) {
# 	    print CONFFILE $_;
# 	    print $_;
# 	}
# 	close CONFFILE;
# 	print "</pre>\n";
# 	print h2("Done");
# 	print end_html,"\n";
# 	exit 0;
#     }
# }

print h3("Hello $curuser,");
my @admgroups;
my $admgroup;
foreach $admgroup (sort grep /-admins$/, keys %{$globals{'groups'}}) {
    if (in_group($admgroup)) {
	push @admgroups, $admgroup;
    }
}
if (@admgroups) {
    print "<p>", "You are administrator for";
    foreach $admgroup (@admgroups) {
	$admgroup =~ /(.*)-admins$/;
	my $therepos = $1;
	if ($repos eq $therepos) {
	    print " [$therepos]";
	} else {
	    print " ", a({-href=>$therepos}, "[$therepos]");
	}
    }
    print ". ";
    print a({-href=>"."}, "General administration")."." if ($repos);
    print "</p>";
}

if ($repos ne "" && in_group("$repos-admins")) {
    print h2({-id=>$repos},"Administrate repository ".
	     a({href=> websvnpath($repos,"/")}, $repos));

    if (in_group("admin")) {
	print start_form(-method => 'post');
	print hidden(-name => 'action', -default => 'adduser', -force => '1');
	print h3("Create Users");
	print "<table style=\"border:1pt solid;\">";
	
	print Tr(td("User (Login):"),
		 td(textfield(-name => "newUser", -default => "",
			      -size => "30", -maxlength => "30")));
	print Tr(td("Full name:"),
		 td(textfield(-name => "fullname", -default => '',
			      -size => '60', -maxlength => '80')));
	print Tr(td("Email:"),
		 td(textfield(-name => "email", -default => '',
			      -size => '60', -maxlength => '180')));
	print Tr(td("Passphrase:"),
		 td(password_field(-name => "pwd", 
				   -size => '32', -maxlength => '80')));
	print Tr(td("Verify passphrase:"),
		 td(password_field(-name => "vpwd", 
				   -size => '32', -maxlength => '80')));
	print "<tr><td rowspan='2'><input type='submit' name='add' value='Add'/></td></tr>";
	print "</table>";
	print end_form;
    }
    
    print start_form(-method => 'post', -enctype => 'multipart/form-data');
    print hidden(-name => 'repos', -default => "$repos", -force =>'1');
    print hidden(-name => 'action', -default => 'chgroupacl', -force => '1');
    print h3("Groups");
    print "<table style=\"border:1pt solid;\">";
    print Tr(th("Group"),th("Users"));
    my @reposgroups = 
	sort grep /^$repos-[a-zA-Z0-9_]+$/, keys %{$globals{'groups'}};
    my $group;
    my $grpnr = 0;
    foreach $group (@reposgroups) {
	$group =~ /^$repos-(.*)$/;
	my $grpname = $1;
	my $users = join(",", @{$globals{'groups'}{$group}});
	print Tr(td(hidden(-name => "grpname[$grpnr]", -default => "$grpname",
                           -force => '1').$group), 
		 td(textfield(-name => "users[$grpnr]", -default => $users, 
			      -size => '50', -force => '1')),
		 td($grpname eq "admins" ? "" : 
		    checkbox(-name => "deletegrp", -value => "$grpnr", 
			     -checked => 0, -force => 1,
			     -label => "Delete")));
	$grpnr++;
    }
    print Tr(td(hidden(-name => 'numgroups', -default => $grpnr, -force =>'1').
		"${repos}-".
		textfield(-name => "grpname[$grpnr]", -default => '', 
			  -force => '1', -size => '15')), 
	     td(scrolling_list(-name => "l_users[$grpnr]",
			       -value => [sort (keys %htpasswd_users)],
			       -labels => {map {$_ => "$_ ($htpasswd_users{$_}[0])" } 
                                               (keys %htpasswd_users)},
			       -size => 5,
			       -multiple => 'true')),
	     td(submit(-name => 'add', -label => 'Add')));
    print Tr(td({-colspan => '3', -align => 'center'}, 
		submit(-name => 'commit', -label => 'Commit Changes')));
    print "</table>";
    
    print h3("Access Control Table");
    print "<table style=\"border:1pt solid;\">";
    
    my $path;
    my $key;
    my $aclnr = 0;
    my $manual = a({href => "/svnbook/svn.serverconfig.httpd.html#svn.serverconfig.httpd.authz.perdir"}, "Manual");
    print Tr(th("Path"),th("User(group)"),th("Access"),th(""));
    foreach $path (sort keys %{$repositories{$repos}}) {
	foreach $key (sort keys %{$repositories{$repos}{$path}}) {
	    my $value = join(",", @{$repositories{$repos}{$path}{$key}});
	    $value = '-' if $value eq '';
	    print Tr(td([hidden(-name => "path[$aclnr]", -value => "$path", 
			        -force => 1) . $path,
	                 hidden(-name => "usergroup[$aclnr]", -value => "$key", 
			        -force => 1) . $key,
			 popup_menu(-name => "access[$aclnr]", 
				    -values => [ 'rw', 'r', '-'], 
				    -default => $value, -force => 1),
			 checkbox(-name => "deleteacl", -value => "$aclnr", 
				  -checked => 0, -force => 1,
				  -label => "Delete")]));
	    $aclnr++;
	}
    }

    print Tr(td([hidden(-name => 'numacl', -default => "$aclnr", -force =>'1').
                 textfield(-name => "path[$aclnr]", -default => '/', 
			   -force =>'1', -size => '30'),
		 popup_menu(-name => "usergroup[$aclnr]",
			    -default => '', -force => 1,
			    -values => [ '', (map { '@'.$_ } @reposgroups),
					 sort (keys %htpasswd_users) ]),
		 popup_menu(-name => "access[$aclnr]",
			    -values => [ 'rw', 'r', '-'],
			    -default => 'rw'),
		 submit(-label => 'Add')]));
    print Tr(td({-colspan => '4', -align => 'center'},
		submit(-name => 'commit', -label => 'Commit Changes')));
    print "</table>";
    print p("You can give read/write or read-only rights to a single user or a user group. A user group is denoted by \@$repos-\&lt;groupname\&gt;.  The access rights are valid for the given path and all sub directories.  For details see the $manual.");
    print p(strong("Warning:"), "the ViewCVS script does not always respect path restrictions.  A skilled user with read-only access to one directory of the repository can read the whole repository.  Better use different repositories.");
    
    if (read_gpg_keys()) {
	print h3("Manage GPG Keys");
	print p("The users in the group $repos-backup can download an encrypted backup ", a({href => "$repos.gpg"}, "$repos.gpg"),". For regular backups you can adapt this ", a({href => "/svnbackup"}, "backup shell script"),". The backup is encrypted with the GPG keys in the following list.");

	print "<table style=\"border:1pt solid;\">";
	my @gpgkeyids = get_gpg_keyid($repos);
	my $id;
	for $id (@gpgkeyids) {
	    print Tr(td($id."&nbsp;".escapeHTML($gpgfpr{$id})),
		     td(checkbox(-name => "gpgdelkey", -value => "$id", 
				 -checked => 0, -force => 1,
				 -label => "Remove")));
	}
	$gpgfpr{""}="";
	print Tr(td(popup_menu(-name => "gpgaddkey",
			       -value => [sort keys %gpgfpr],
			       -force => '1',
			       -labels => {map {$_ => "$_ $gpgfpr{$_}" } 
                                               (keys %gpgfpr)})),
		 td(submit(-name => 'add', -label => 'Add')));

	print Tr(td([strong("GPG Public Key: ").
		     filefield(-name => 'gpgkeyfile', -default => '', 
			       -size => '40')]));
	print Tr(td({-colspan => '2', -align => 'center'},
		    submit(-name => 'commit', -label => 'Commit Changes')));
	print "</table>";
    }
    print endform;


    print h3("Get/Upload dump file");
    print p("Click here, to download a ".
	    a({href => "$repos.gz"}, "dump file").
	    " of repository $repos");
    print p("Upload an ",b("incremental"),
	    " dump file into repository $repos:"),
    start_form(-method=>"post", -enctype=>"multipart/form-data"), 
    hidden(-name => 'action', -default => 'load', -force =>'1'),
    hidden(-name => 'repos', -default => "$repos", -force =>'1'),
    table(Tr([td([strong("Dump File: "),
		  filefield(-name => 'dumpfile', -default => '', 
			    -size => '40')]),
	      td([strong("Subdirectory: "),
		  textfield(-name => 'dumpsubdir', -default => '', 
			    -size => '20')])
	      ])),
		  submit(-label => 'Load'),
		  end_form;
    
    print hr;
    
    
# 	print h3("Get/Upload configuration file");
# 	print p("Click here, to download ".
# 		a({href => "$repos/svnserve.conf"}, "svnserve.conf").
# 		" of repository $repos");
# 	print p("Upload a new svnserve.conf into repository $repos:"),
# 	start_form(-method=>"post", -enctype=>"multipart/form-data"), 
# 	hidden(-name => 'action', -default => 'loadconf', -force =>'1'),
# 	hidden(-name => 'repos', -default => "$repos", -force =>'1'),
# 	table(Tr([td([strong("Config File: "),
# 		      filefield(-name => 'conffile', -default => '', 
# 				-size => '40')]),
# 	      ])),
# 	submit(-label => 'Load'),
# 	end_form;

# 	print hr;

} elsif ($repos eq "") {

    print h2("Change Passphrase"),"\n";
    print p("please enter your new choice of passphrase below, and then verify it by entering it again."),"\n",
    start_form,
    hidden(-name => 'action', -default => "changepw"),
    table(Tr([
	      td([strong("Passphrase: "),
		  password_field(-name => 'passphrase', -size => 32, -maxlength => 80),
		  "(6-80 chars)"]),
	      td([strong("Verify: "),
		  password_field(-name => 'verify', -size => 32, -maxlength => 80)])
	      ])),
    submit(-label => 'change passphrase'),
    end_form,
    "\n",p("You can either use a passphrase (preferably of decent length, include punctuation, etc,) or a password.  Good passwords have these properties:"),"\n",
    ul(
     li('is not based upon a dictionary word'),
     li('does not have numbers substituted for common letters (ie. 3 for E 1 for I, 0 for O, etc) or numbers used as a suffix/prefix (ie.  4sale, 2by4, etc.)'),
     li('is at least 8 characters long (length of 6 to 80 is required)'),
     li('is made up of a combination of non-repeating upper/lower case letters, numbers, and punctuation.'),
     li('is hard to guess ;)'),
    ),
    "\n",p,"Also note that the passphrase is case-sensitive.\n",hr;

    if (in_group("admin")) {
	print h2("Create a new repository");
	print start_form, 
	hidden(-name => 'action', -default => 'create', -force =>'1'),
	table(Tr([td([strong("Name of new repository: "),
		  textfield(-name => 'repos', -default => '', 
			    -size => '20')]),
		  td([strong("Administrator: "),
		      textfield(-name => 'reposadmin', -default => "$curuser", 
				-size => '20')])
	      ])),
		      submit(-label => 'Create'),
		      end_form,hr;
    }
    
    {
	my $key;
	print h2("Your access rights"),
	p("You have ", strong("read-write")," access to the following repositories:"),"<ul>";
	foreach $repos (sort keys %repositories) {
	    foreach $path (sort keys %{$repositories{$repos}}) {
		foreach $key (sort keys %{$repositories{$repos}{$path}}) {
		    next if @{$repositories{$repos}{$path}{$key}} != 1;
		    next if $repositories{$repos}{$path}{$key}[0] ne "rw";
		    if ($key eq $curuser
			|| $key eq '*'
			|| ($key =~ /^@(.*)$/ && in_group("$1"))) {
			print li(a({href => websvnpath($repos,$path)}, 
				   "$baseurl${svnpath}/$repos$path"));
		    }
		}
	    }
	}
	print "</ul>",
	p("You have ", strong("read-only")," access to the following repositories:"),"<ul>";
	foreach $repos (sort keys %repositories) {
	    foreach $path (sort keys %{$repositories{$repos}}) {
		foreach $key (sort keys %{$repositories{$repos}{$path}}) {
		    next if @{$repositories{$repos}{$path}{$key}} != 1;
		    next if $repositories{$repos}{$path}{$key}[0] ne "r";
		    if ($key eq $curuser || $key eq '*'
			|| ($key =~ /^@(.*)$/ && in_group("$1"))) {
			print li(a({href => websvnpath($repos,$path)}, 
				   "$baseurl${svnpath}/$repos$path"));
		    }
		}
	    }
	}
	print "</ul>",hr;
    }
}
print p("<small>Copyright 2005&ndash;2009 Jochen Hoenicke, Michael M&ouml;ller, Marco L&uuml;bcke; based on code from Theo Van Dinter</small>"),"\n";
print end_html,"\n";
