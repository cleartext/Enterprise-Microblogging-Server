CREATE TABLE subscribers(
    user VARCHAR(250) NOT NULL,
    subscriber VARCHAR(250) NOT NULL,
    PRIMARY KEY (user, subscriber)
) ENGINE=InnoDB, CHARSET=utf8;

-- add jid and presence fields
ALTER TABLE users ADD jid VARCHAR(255) DEFAULT '', ADD presence BOOLEAN DEFAULT FALSE;
UPDATE users SET jid = concat(username, '@example.com');
CREATE UNIQUE INDEX by_jid ON users (jid);

-- Table to store realtime searches
CREATE TABLE search_terms (
    term VARCHAR(255) NOT NULL,
    username VARCHAR(250) NOT NULL,
    PRIMARY KEY (term, username)
) ENGINE=InnoDB, CHARSET=utf8;

-- Table to store latest users tweets (to display them in the web interface)
CREATE TABLE tweets(
    id INTEGER NOT NULL AUTO_INCREMENT,
    username VARCHAR(250) NOT NULL,
    text TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id)
) ENGINE = InnoDB, CHARSET=utf8;

CREATE INDEX by_user ON tweets (username);
