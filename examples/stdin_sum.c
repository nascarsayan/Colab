// Demonstrate forwarded stdin and separate stdout/stderr. This example is CPU code.
// printf '12 30\n' | Colab run examples/stdin_sum.c
#include <stdio.h>
int main(void) {
    int a, b;
    fprintf(stderr, "Enter two integers between -1000000 and 1000000:\n");
    if (scanf("%d %d", &a, &b) != 2 || a < -1000000 || a > 1000000 || b < -1000000 || b > 1000000) {
        fprintf(stderr, "Invalid input\n"); return 2;
    }
    printf("sum = %d\n", a + b);
    return 0;
}
