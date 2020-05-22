#!/usr/bin/python3
# -*- indent-tabs-mode: t; tab-width: 4; python-indent-offset: 4; -*-

#
# helper functions for migration #13
#

import uuid, os, sqlite3, ldap3


def add_user(env, ldapconn, search_base, users_base, domains_base, email, password, privs, cn=None):
	# Add a sqlite user to ldap
	#   env are the environment variables
	#   ldapconn is the bound ldap connection
	#   search_base is for finding a user with the same email
	#   users_base is the rdn where the user will be added
	#   domains_base is the rdn for 'domain' entries
	#   email is the user's email
	#   password is the user's current sqlite password hash
	#   privs is an array of privilege names for the user
	#   cn is the user's common name [optional]
	#
	# the email address should be as-is from sqlite (encoded as
	# ascii using IDNA rules)

	# If the email address exists, return and do nothing
	ldapconn.search(search_base, "(mail=%s)" % email)
	if len(ldapconn.entries) > 0:
		print("user already exists: %s" % email)
		return ldapconn.response[0]['dn']

	# Generate a unique id for uid
	uid = '%s' % uuid.uuid4()

	# Attributes to apply to the new ldap entry
	attrs = {
		"mail" : email,
		"maildrop" : email,
		"uid" : uid,
		# Openldap uses prefix {CRYPT} for all crypt(3) formats
		"userPassword" : password.replace('{SHA512-CRYPT}','{CRYPT}')
	}

	# Add privileges ('mailaccess' attribute)
	privs_uniq = {}
	for priv in privs:
		if priv.strip() != '': privs_uniq[priv] = True
	if len(privs_uniq) > 0:
		attrs['mailaccess'] = privs_uniq.keys()

	# Get a common name
	localpart, domainpart = email.split("@")

	if cn is None:
		# Get the name for the email address from Roundcube and
		# use that or `localpart` if no name
		rconn = sqlite3.connect(os.path.join(env["STORAGE_ROOT"], "mail/roundcube/roundcube.sqlite"))
		rc = rconn.cursor()
		rc.execute("SELECT name FROM identities WHERE email = ? AND standard = 1 AND del = 0 AND name <> ''", (email,))
		rc_all = rc.fetchall()
		if len(rc_all)>0:
			cn = rc_all[0][0]
			attrs["displayName"] = cn
		else:
			cn = localpart.replace('.',' ').replace('_',' ')
		rconn.close()
	attrs["cn"] = cn

	# Choose a surname for the user (required attribute)
	attrs["sn"] = cn[cn.find(' ')+1:]

	# Add user
	dn = "uid=%s,%s" % (uid, users_base)
	print("adding user %s" % email)
	ldapconn.add(dn,
		     [ 'inetOrgPerson','mailUser','shadowAccount' ],
		     attrs);			 

	# Create domain entry indicating that we are handling
	# mail for that domain
	domain_dn = 'dc=%s,%s' % (domainpart, domains_base)
	try:
		ldapconn.add(domain_dn, [ 'domain' ], {
			"businessCategory": "mail"
		})
	except ldap3.core.exceptions.LDAPEntryAlreadyExistsResult:
		pass
	return dn


def create_users(env, conn, ldapconn, ldap_base, ldap_users_base, ldap_domains_base):
	# iterate through sqlite 'users' table and create each user in
	# ldap. returns a map of email->dn
	c = conn.cursor()
	c.execute("SELECT email,password,privileges from users")
	users = {}
	for row in c:
		email=row[0]
		password=row[1]
		privs=row[2]
		dn = add_user(env, ldapconn, ldap_base, ldap_users_base, ldap_domains_base, email, password, privs.split("\n"))
		users[email] = dn
	return users


def create_aliases(conn, ldapconn, aliases_base):
	# iterate through sqlite 'aliases' table and create ldap
	# aliases but without members.  returns a map of alias->dn
	aliases={}
	c = conn.cursor()
	for row in c.execute("SELECT source FROM aliases WHERE destination<>''"):
		alias=row[0]
		ldapconn.search(aliases_base, "(mail=%s)" % alias)
		if len(ldapconn.entries) > 0:
			# Already present
			print("alias already exists %s" % alias)
			aliases[alias] = ldapconn.response[0]['dn']
		else:
			cn="%s" % uuid.uuid4()
			dn="cn=%s,%s" % (cn, aliases_base)
			print("adding alias %s" % alias)
			ldapconn.add(dn, ['mailGroup'], {
				"mail": alias,
				"description": "Mail group %s" % alias
			})
			aliases[alias] = dn
	return aliases


def populate_aliases(conn, ldapconn, users_map, aliases_map):
	# populate alias with members.
	# conn is a connection to the users sqlite database
	# ldapconn is a connecton to the ldap database
	# users_map is a map of email -> dn for every user on the system
	# aliases_map is a map of email -> dn for every pre-created alias
	#
	# email addresses should be encoded as-is from sqlite (IDNA
	# domains)
	c = conn.cursor()
	for row in c.execute("SELECT source,destination FROM aliases where destination<>''"):
		alias=row[0]
		alias_dn=aliases_map[alias]
		members = []
		mailMembers = []
		
		for email in row[1].split(','):
			email=email.strip()
			if email=="":
				continue
			elif email in users_map:
				members.append(users_map[email])
			elif email in aliases_map:
				members.append(aliases_map[email])
			else:
				mailMembers.append(email)
		
		print("populate alias group %s" % alias)
		changes = {}
		if len(members)>0:
			changes["member"]=[(ldap3.MODIFY_REPLACE, members)]
		if len(mailMembers)>0:
			changes["rfc822MailMember"]=[(ldap3.MODIFY_REPLACE, mailMembers)]			
		ldapconn.modify(alias_dn, changes)


def add_permitted_senders_group(ldapconn, users_base, group_base, source, permitted_senders):
	# creates a single permitted_senders ldap group
	#
	# email addresses should be encoded as-is from sqlite (IDNA
	# domains)

	# If the group already exists, return and do nothing
	ldapconn.search(group_base, "(&(objectClass=mailGroup)(mail=%s))" % source)
	if len(ldapconn.entries) > 0:
		return ldapconn.response[0]['dn']

	# get a dn for every permitted sender
	permitted_dn = {}
	for email in permitted_senders:
		email = email.strip()
		if email == "": continue
		ldapconn.search(users_base, "(mail=%s)" % email)
		for result in ldapconn.response:
			permitted_dn[result["dn"]] = True
	if len(permitted_dn) == 0:
		return None

	# add permitted senders group for the 'source' email
	gid = '%s' % uuid.uuid4()
	group_dn = "cn=%s,%s" % (gid, group_base)
	print("adding permitted senders group for %s" % source)
	try:
		ldapconn.add(group_dn, [ "mailGroup" ], {
			"cn" : gid,
			"mail" : source,
			"member" : permitted_dn.keys(),
			"description": "Permitted to MAIL FROM this address"
		})
	except ldap3.core.exceptions.LDAPEntryAlreadyExistsResult:
		pass
	return group_dn


def create_permitted_senders(conn, ldapconn, users_base, group_base):
	# iterate through the 'aliases' table and create all
	# permitted-senders groups
	c = conn.cursor()
	c.execute("SELECT source, permitted_senders from aliases WHERE permitted_senders is not null")
	groups={}
	for row in c:
		source=row[0]
		senders=[]
		for line in row[1].split("\n"):
			for sender in line.split(","):
				if sender.strip() != "":
					senders.append(sender.strip())
		dn=add_permitted_senders_group(ldapconn, users_base, group_base, source, senders)
		if dn is not None:
			groups[source] = dn
	return groups
