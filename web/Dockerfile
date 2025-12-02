FROM nginx:alpine

WORKDIR /usr/share/nginx/html

# Poistetaan oletuskonffi
RUN rm /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html app.js ./
