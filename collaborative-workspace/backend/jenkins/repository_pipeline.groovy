pipeline {
    agent any
    options {
        disableConcurrentBuilds()
        timeout(time: 45, unit: 'MINUTES')
    }
    environment {
        REPOSITORY_URL = @@REPOSITORY_URL@@
        SOURCE_BRANCH = @@SOURCE_BRANCH@@
        PROJECT_SLUG = @@PROJECT_SLUG@@
        GITHUB_CREDENTIALS_ID = @@CREDENTIALS_ID@@
        CONTAINER_PORT = '@@CONTAINER_PORT@@'
        DEPLOY_NETWORK = 'project-k-deploy'
        DEPLOY_PROXY = 'project-k-deployment-proxy'
        DEPLOY_CONFIG = '/deployment-config'
    }
    stages {
        stage('Checkout') {
            steps {
                script {
                    def remote = [url: env.REPOSITORY_URL]
                    if (env.GITHUB_CREDENTIALS_ID?.trim()) {
                        remote.credentialsId = env.GITHUB_CREDENTIALS_ID
                    }
                    checkout([$class: 'GitSCM',
                        branches: [[name: "*/${env.SOURCE_BRANCH}" ]],
                        userRemoteConfigs: [remote]
                    ])
                }
            }
        }
        stage('Build') {
            steps {
                script {
                    if (!fileExists('Dockerfile')) {
                        def fallbackDockerfile = @@DOCKERFILE_TEXT@@
                        if (!fallbackDockerfile) {
                            error('This project needs a Dockerfile before Jenkins can build it.')
                        }
                        writeFile file: 'Dockerfile', text: fallbackDockerfile
                    }
                }
                sh '''set -eu
revision="$(git rev-parse --short=12 HEAD)"
image="project-k-${PROJECT_SLUG}:${revision}-${BUILD_NUMBER}"
candidate="${PROJECT_SLUG}-${BUILD_NUMBER}-${revision}"
docker build -t "$image" .
old_containers="$(docker ps -q --filter "label=projectk.project=${PROJECT_SLUG}")"
docker run -d --name "$candidate" --network "$DEPLOY_NETWORK" \
  --label "projectk.project=${PROJECT_SLUG}" \
  --label "projectk.revision=${revision}" "$image"

healthy=0
for attempt in $(seq 1 30); do
    if curl --silent --show-error --fail "http://${candidate}:${CONTAINER_PORT}/" >/dev/null; then
        healthy=1
        break
    fi
    sleep 2
done
if [ "$healthy" -ne 1 ]; then
    docker rm -f "$candidate" >/dev/null 2>&1 || true
    echo "Candidate failed its HTTP health check" >&2
    exit 1
fi

config="${DEPLOY_CONFIG}/${PROJECT_SLUG}.conf"
backup="${config}.previous"
tmp="${config}.tmp"
had_config=0
if [ -f "$config" ]; then
    cp "$config" "$backup"
    had_config=1
fi
cat > "$tmp" <<EOF
upstream projectk_${PROJECT_SLUG}_backend {
    server ${candidate}:${CONTAINER_PORT};
    keepalive 32;
}
server {
    listen 8080;
    server_name ${PROJECT_SLUG}.localhost;
    location / {
        proxy_pass http://projectk_${PROJECT_SLUG}_backend;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
mv "$tmp" "$config"
if ! docker exec "$DEPLOY_PROXY" nginx -t; then
    if [ "$had_config" -eq 1 ]; then mv "$backup" "$config"; else rm -f "$config"; fi
    docker rm -f "$candidate" >/dev/null 2>&1 || true
    exit 1
fi
if ! docker exec "$DEPLOY_PROXY" nginx -s reload; then
    if [ "$had_config" -eq 1 ]; then mv "$backup" "$config"; else rm -f "$config"; fi
    docker exec "$DEPLOY_PROXY" nginx -s reload >/dev/null 2>&1 || true
    docker rm -f "$candidate" >/dev/null 2>&1 || true
    exit 1
fi
rm -f "$backup"
sleep 2
for old in $old_containers; do
    [ -n "$old" ] || continue
    docker stop --time 120 "$old" >/dev/null 2>&1 || true
    docker rm "$old" >/dev/null 2>&1 || true
done
echo "Deployment active at http://${PROJECT_SLUG}.localhost:5002"
'''
            }
        }
    }
}
