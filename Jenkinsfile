pipeline {
    agent any

    environment {
        DOCKER_IMAGE          = "withthanks-django"
        IMAGE_TAG             = "1.0.0"
        CONTAINER_NAME        = "withthanks-container"
        APP_PORT              = "8000"
        HOST_UPLOAD_PATH      = "/var/jenkins_home/uploads/video-generation/uploads"
        CONTAINER_UPLOAD_PATH = "/app/media"
        DOCKER_HUB_USER       = "rankraze"
    }

    stages {
        stage('Checkout Code') {
            steps {
                git branch: 'main',
                    credentialsId: 'github-creds-1',
                    url: 'https://github.com/Rajachellan/WithThanks.git'
            }
        }

        stage('Docker Login') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'dockerhub-creds',
                    usernameVariable: 'DOCKER_USER',
                    passwordVariable: 'DOCKER_PASS'
                )]) {
                    sh '''
                    echo $DOCKER_PASS | docker login -u $DOCKER_USER --password-stdin
                    '''
                }
            }
        }

        stage('Build & Push Docker Image') {
            steps {
                sh """
                docker build -t ${DOCKER_IMAGE}:${IMAGE_TAG} .
                docker tag ${DOCKER_IMAGE}:${IMAGE_TAG} ${DOCKER_HUB_USER}/${DOCKER_IMAGE}:${IMAGE_TAG}
                docker tag ${DOCKER_IMAGE}:${IMAGE_TAG} ${DOCKER_HUB_USER}/${DOCKER_IMAGE}:latest
                docker push ${DOCKER_HUB_USER}/${DOCKER_IMAGE}:${IMAGE_TAG}
                docker push ${DOCKER_HUB_USER}/${DOCKER_IMAGE}:latest
                """
            }
        }

        stage('Stop Old Container') {
            steps {
                sh """
                echo "Stopping old container if exists..."
                docker stop ${CONTAINER_NAME} || true
                docker rm ${CONTAINER_NAME} || true
                """
            }
        }

        stage('Ensure Host Upload Folder') {
            steps {
                sh """
                echo "Ensuring uploads folder exists on host..."
                mkdir -p ${HOST_UPLOAD_PATH}
                chmod -R 777 ${HOST_UPLOAD_PATH} || true
                """
            }
        }

        stage('Run Container') {
            steps {
                withCredentials([file(credentialsId: 'django-env-file', variable: 'ENV_FILE')]) {
                    sh """
                    echo "Running new Django container..."
                    docker run -d \
                        --name ${CONTAINER_NAME} \
                        --restart always \
                        -p ${APP_PORT}:8000 \
                        --env-file \$ENV_FILE \
                        -v ${HOST_UPLOAD_PATH}:${CONTAINER_UPLOAD_PATH} \
                        ${DOCKER_HUB_USER}/${DOCKER_IMAGE}:${IMAGE_TAG}
                    """
                }
            }
        }

        stage('Run Django Migrations') {
            steps {
                sh """
                echo "Running Django migrations..."
                docker exec -i ${CONTAINER_NAME} python manage.py migrate --noinput
                """
            }
        }

        stage('Health Check') {
            steps {
                sh """
                echo "Checking if container is running..."
                retries=5
                until [ "\$(docker inspect -f '{{.State.Running}}' ${CONTAINER_NAME})" = "true" ] || [ \$retries -le 0 ]; do
                    echo "Waiting for container to start..."
                    sleep 5
                    retries=\$((retries-1))
                done

                if [ \$retries -le 0 ]; then
                    echo "❌ Container failed to start!"
                    docker logs ${CONTAINER_NAME}
                    exit 1
                fi
                echo "✅ Container is running."
                """
            }
        }

        stage('Verify Upload Folder') {
            steps {
                sh """
                echo "Verifying uploads folder..."
                if [ -d "${HOST_UPLOAD_PATH}" ]; then
                    echo "✅ Uploads folder exists on host."
                else
                    echo "❌ Uploads folder does NOT exist!"
                    exit 1
                fi
                """
            }
        }
    }

    post {
        success {
            echo "✅ WithThanks Django app deployed successfully at http://localhost:${APP_PORT}/"
        }
        failure {
            echo "❌ Deployment failed!"
            sh "docker logs ${CONTAINER_NAME} || true"
        }
    }
}
