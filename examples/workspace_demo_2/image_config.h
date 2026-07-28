#ifndef IMAGE_CONFIG_H_
#define IMAGE_CONFIG_H_



// Camera output size. Keep these values consistent with the MT9V03X driver.
#define IMG_W   186
#define IMG_H   70

// Processing image size and its top-left position in the camera image.
// Example: 186 x 70, starting at (1, 5), removes one column from each side,
// five rows from the top, and 45 rows from the bottom of a 188 x 120 image.
#include <stdlib.h>
#include "basic_process.h"

#include "identify.h"
#include "lane_repair.h"

#define BLACK       ((uint8_t)0U)
#define WHITE       ((uint8_t)255U)

#endif /* IMAGE_CONFIG_H_ */
