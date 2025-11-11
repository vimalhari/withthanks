pipeline {
    agent any

    environment {
        DOCKER_IMAGE = "withthanks-django"
        IMAGE_TAG = "1.0.0"
        CONTAINER_NAME = "withthanks-container"
        APP_PORT = "8000"
        DOCKER_HUB_USER = "rankraze"   // your Docker Hub username
        UPLOADS_PATH = "/home/rankraze/uploads/video-generation/uploads" // must exist & writable by Jenkins
    }

    stages {

        stage('Checkout Code') {
            steps {
                echo "📂 Checking out source code..."
                git branch: 'main',
                    credentialsId: 'github-creds-1',
                    url: 'https://github.com/Rajachellan/WithThanks.git'
            }
        }

        stage('Docker Login') {
            steps {
                echo "🔐 Logging in to Docker Hub..."
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
                echo "🐳 Building Docker image..."
                sh '''
                docker build -t $DOCKER_IMAGE:$IMAGE_TAG .

                echo "🏷️ Tagging image..."
                docker tag $DOCKER_IMAGE:$IMAGE_TAG $DOCKER_HUB_USER/$DOCKER_IMAGE:$IMAGE_TAG
                docker tag $DOCKER_IMAGE:$IMAGE_TAG $DOCKER_HUB_USER/$DOCKER_IMAGE:latest

                echo "🚀 Pushing image to Docker Hub..."
                docker push $DOCKER_HUB_USER/$DOCKER_IMAGE:$IMAGE_TAG
                docker push $DOCKER_HUB_USER/$DOCKER_IMAGE:latest
                '''
            }
        }

        stage('Prepare Uploads Directory') {
            steps {
                echo "📁 Ensuring uploads directory exists and is writable..."
                sh '''
                mkdir -p $UPLOADS_PATH
                chmod 775 $UPLOADS_PATH
                chown jenkins:jenkins $UPLOADS_PATH || true
                ls -ld $UPLOADS_PATH
                '''
            }
        }

        stage('Stop Old Container') {
            steps {
                echo "🛑 Stopping and removing old container if running..."
                sh '''
                docker stop $CONTAINER_NAME || true
                docker rm $CONTAINER_NAME || true
                '''
            }
        }

        stage('Run New Container') {
            steps {
                echo "🚀 Starting new Django container using Jenkins secret .env file..."
                withCredentials([file(credentialsId: 'django-env-file', variable: 'ENV_FILE')]) {
                    sh '''
                    echo "🧩 Using .env file from Jenkins secrets..."
                    docker run -d --name $CONTAINER_NAME \
                        --restart always \
                        -p $APP_PORT:8000 \
                        --env-file $ENV_FILE \
                        -v $UPLOADS_PATH:$UPLOADS_PATH \
                        $DOCKER_HUB_USER/$DOCKER_IMAGE:$IMAGE_TAG
                    '''
                }
            }
        }

        stage('Run Django Migrations') {
            steps {
                echo "🛠 Running Django migrations inside the container..."
                sh '''
                docker exec -i $CONTAINER_NAME python manage.py migrate --noinput
                '''
            }
        }

        stage('Check Container Logs') {
            steps {
                echo "📄 Checking container logs for errors..."
                sh '''
                docker logs $CONTAINER_NAME || true
                '''
            }
        }
    }

    post {
        success {
            echo "✅ Deployment successful! App running on port $APP_PORT"
        }
        failure {
            echo "❌ Deployment failed! Check Jenkins logs."
        }
        always {
            echo "📋 Pipeline finished at ${new Date()}"
        }
    }
}
