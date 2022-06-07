# Graffiti Server

## Local Usage

To launch the server locally, run:

    sudo docker compose up --build

The application will be up at [http://localhost:5000](http://localhost:5000).
If you are using the [Vue.js Graffiti plugin](https://github.com/csail-graffiti/vue), you might point to the local server as follows:

    Graffiti("http://localhost:5000").then(g=>createApp().use(g).mount("#app")

## Contribution

### Design Overview

The codebase consists of three modules: `auth`, `app`, and `broker`. Each module has its own folder and exists as a separate docker container. A docker compose file hooks the three modules together along with [MongoDB](https://www.mongodb.com/), [Redis](https://redis.io/), [nginx](https://nginx.org/en/) and [docker-mailserver](https://docker-mailserver.github.io/docker-mailserver/edge/) to form a complete application.

#### `auth`

implements the [OAuth2](https://www.oauth.com/) standard to authorize users with the server. Users log in by clicking a link sent to their email so no passwords are stored on the server. `auth` is served at `auth.DOMAIN`.

#### `app`

exposes the Graffiti database API via a websocket served at `app.DOMAIN`. The API consists of 4 basic functions:

- `update`: lets users insert or replace objects they have put in the database.
- `delete`: lets users remove objects they have put in the database.
- `subscribe`: returns all database entries matching a query and then continues to stream new matches as they arrive.
- `unsubscribe`: stops streaming results from a particular `subscribe` request.

Objects are schemaless aside from 4 regulated fields:

- `_id`: a unique identifier randomly generated by the server.
- `_by`: a field that, if included, must be equal to the user's identifier returned by the `auth` module — users can only create objects `_by` themselves.
- `_to`: a field that, if included, must be equal to a list of user identifiers. If this field is included in a query it must be equal to the querier's identifier — users can only query for objects `_to` themselves.
- `_contexts`: this field must be a list of objects each of which may contain a `_nearMisses` and a `_neighbors` field. These subfields must each be lists of objects. The `_contexts` field cannot be matched directly by a query. Instead, a query matches an object if for each of its contexts, each near miss object *does not* match the query and each neighbor object *does* match the query. This allows users to limit the set of queries that match their object, which can create virtual boundaries between different information spaces.

#### `broker`

is the critical path of the server. Whenever any object is added or removed from the database that object's ID is sent to the broker. The broker matches changed objects with all queries that are currently being subscribed to and then publishes those changes back to `app` to send as results of the `subscribe` function. Optimizing this module will probably yield the most performance gains.

### Testing

There are a series of test scripts in the `app/test` folder which you can run as follows

    docker compose exec graffiti-app app/test/schema.py

### Wishlist

It would be really nice if someone implemented...

- An interface to import and export one's own data from the server, perhaps to a git repository.
- Bridges that carry over data from existing social platforms into the Graffiti ecosystem.
- Better scaling so the server could operate over multiple machines with multiple instances of each module. Perhaps this involves Kubernetes and AWS...

## Deployment

### Dependencies

On your server install:

- Docker Engine including the Docker Compose plugin via [these instructions](https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository).
- Certbot according to [these instructions](https://certbot.eff.org/instructions?ws=other&os=ubuntufocal).

### Configuration

Clone this repository onto the server and edit the following variables in the `.env` file.

- `DOMAIN`: this should be the domain that points to your server, *e.g.* `graffiti.csail.mit.edu`. 
- `SECRET`: this is used to authenticate users with the server. Make it unique and **keep it safe**!

### SSL

Add CNAME entries for the `app.DOMAIN` and `auth.DOMAIN` subdomains by adding these lines to your DNS (where `DOMAIN` is replaced with your server's domain):

    app.DOMAIN.  1800 IN CNAME DOMAIN
    auth.DOMAIN. 1800 IN CNAME DOMAIN

Once these changes propagate (it might take up to an hour), generate SSL certificates with:

    sudo certbot certonly --standalone -d DOMAIN,app.DOMAIN,auth.DOMAIN

This will generate the following files:

    /etc/letsencrypt/live/DOMAIN/fullchain.pem
    /etc/letsencrypt/live/DOMAIN/privkey.pem

### Mailserver

First launch the server:

    sudo docker compose -f docker-compose.yml -f docker-compose.deploy.yml up --build

Once the docker application is running, create domain keys for the mail server:

    sudo docker exec graffiti-mailserver setup config dkim

Copy the generated entry in `config/mailserver/opendkim/keys/DOMAIN/mail.txt` to your DNS.
To get things to work on the [CSAIL DNS](https://webdns.csail.mit.edu/), the entire `mail.txt` needs to be on a single line, but split up into segments of less than 256 characters.
The generated file should already be split, but the sections are on new lines. Replace the new lines with spaces so it looks like this:

    mail._domainkey.DOMAIN. 1800 IN TXT "v=DKIM1; h=sha256; k=rsa; p=" "MII...SiL" "6yL...UND" ...

In addition, add these lines to your DNS to turn on the email security features DKIM and SPF:

    _domainkey.DOMAIN. 1800 IN TXT "o=-"
    DOMAIN. 1800 IN TXT "v=spf1 a -all"

Once the DNS propagates (again, it might take an hour), you can test that the mail server is working by going to
`https://auth.DOMAIN/client_id=&redirect_uri=`.
Send an email to `test@allaboutspam.com` then go to [All About Spam](http://www.allaboutspam.com/email-server-test-report/index.php) and enter `noreply@DOMAIN` to see your test report.

### Launching

Once everything is set up, you can start the server by running

    sudo docker compose -f docker-compose.yml -f docker-compose.deploy.yml up --build

and shut it down by running

    sudo docker compose down --remove-orphans
